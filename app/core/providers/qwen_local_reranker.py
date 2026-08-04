from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
)

_BACKEND = "qwen_local"
_DEFAULT_TASK = "Given a web search query, retrieve relevant passages that answer the query"


class QwenLocalReranker(RerankerPort):
    """Lazy local adapter; importing this module never imports torch/transformers."""

    def __init__(
        self,
        *,
        model_id: str,
        device: str = "cuda",
        score_fn: Callable[[str, Sequence[str]], Sequence[float]] | None = None,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._score_fn = score_fn
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    async def rerank(self, request: RerankRequest) -> list[RankedDocument]:
        top_n = _validate_request(request)
        if not request.documents:
            return []
        try:
            scores = await asyncio.to_thread(self._score, request.query, request.documents)
        except TerminalRerankerError:
            raise
        except Exception as exc:
            raise TerminalRerankerError("Qwen reranker inference failed", backend=_BACKEND) from exc
        if len(scores) != len(request.documents):
            raise TerminalRerankerError("Qwen reranker returned the wrong score count", backend=_BACKEND)
        ordered = sorted(enumerate(scores), key=lambda item: (-float(item[1]), item[0]))[:top_n]
        return [
            RankedDocument(index=index, rank=rank, relevance_score=float(score))
            for rank, (index, score) in enumerate(ordered, start=1)
        ]

    def _score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        if self._score_fn is not None:
            return self._score_fn(query, documents)
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise TerminalRerankerError(
                "Qwen optional dependencies are not installed",
                backend=_BACKEND,
            ) from exc

        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_id, padding_side="left")
            dtype = torch.float16 if self._device.startswith("cuda") else "auto"
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_id,
                torch_dtype=dtype,
            ).to(self._device).eval()

        prefix = (
            '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
            'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
            "<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        pairs = [
            f"{prefix}<Instruct>: {_DEFAULT_TASK}\n<Query>: {query}\n<Document>: {document}{suffix}"
            for document in documents
        ]
        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            logits = self._model(**inputs).logits[:, -1, :]
            false_id = self._tokenizer.convert_tokens_to_ids("no")
            true_id = self._tokenizer.convert_tokens_to_ids("yes")
            binary_logits = torch.stack([logits[:, false_id], logits[:, true_id]], dim=1)
            return torch.nn.functional.log_softmax(binary_logits, dim=1)[:, 1].exp().tolist()


def _validate_request(request: RerankRequest) -> int:
    if not request.query.strip():
        raise TerminalRerankerError("rerank query must not be empty", backend=_BACKEND)
    if any(not document.strip() for document in request.documents):
        raise TerminalRerankerError("rerank documents must not be empty", backend=_BACKEND)
    top_n = len(request.documents) if request.top_n is None else request.top_n
    if top_n < 0 or top_n > len(request.documents):
        raise TerminalRerankerError("top_n is outside the document range", backend=_BACKEND)
    return top_n
