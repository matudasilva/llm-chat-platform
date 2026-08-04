from __future__ import annotations

import builtins
import importlib
import json
import sys
from typing import Any

from botocore.exceptions import ClientError
import httpx
import pytest

from app.core.domain.reranker import (
    RankedDocument,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.gcp_reranker import GcpReranker


async def _token() -> str:
    return "test-token"


def _gcp_client(status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 200:
            return httpx.Response(
                200,
                json={
                    "records": [
                        {"id": "1", "score": 0.9},
                        {"id": "0", "score": 0.2},
                    ]
                },
            )
        return httpx.Response(status_code, json={"error": {"status": "failure"}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _AwsClient:
    def __init__(self, *, error_code: str | None = None) -> None:
        self.error_code = error_code
        self.request: dict[str, Any] | None = None

    def rerank(self, **kwargs: Any) -> dict[str, Any]:
        self.request = kwargs
        if self.error_code:
            raise ClientError(
                {"Error": {"Code": self.error_code, "Message": "redacted"}},
                "Rerank",
            )
        return {
            "results": [
                {"index": 1, "relevanceScore": 0.8},
                {"index": 0, "relevanceScore": 0.1},
            ]
        }


@pytest.mark.parametrize("backend", ["gcp", "aws", "qwen"])
async def test_all_adapters_satisfy_the_same_contract(backend: str) -> None:
    if backend == "gcp":
        reranker = GcpReranker(
            project_id="project",
            access_token_provider=_token,
            http_client=_gcp_client(),
        )
    elif backend == "aws":
        reranker = AwsReranker(client=_AwsClient())
    else:
        from app.core.providers.qwen_local_reranker import QwenLocalReranker

        reranker = QwenLocalReranker(
            model_id="Qwen/Qwen3-Reranker-0.6B",
            score_fn=lambda query, documents: [0.1, 0.8],
        )

    results = await reranker.rerank(
        RerankRequest(query="answer", documents=("wrong", "answer"), top_n=2)
    )

    assert results == [
        RankedDocument(index=1, rank=1, relevance_score=pytest.approx(0.9 if backend == "gcp" else 0.8)),
        RankedDocument(index=0, rank=2, relevance_score=pytest.approx(0.1 if backend != "gcp" else 0.2)),
    ]


async def test_gcp_adapter_sends_stable_ids_and_content() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"records": [{"id": "0", "score": 0.5}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = GcpReranker(project_id="project", access_token_provider=_token, http_client=client)

    await reranker.rerank(RerankRequest(query="query", documents=("document",), top_n=1))

    assert captured is not None
    assert captured.headers["authorization"] == "Bearer test-token"
    assert captured.headers["x-goog-user-project"] == "project"
    body = json.loads(captured.content)
    assert body["records"] == [{"id": "0", "content": "document"}]


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(403, TerminalRerankerError), (429, TransientRerankerError), (503, TransientRerankerError)],
)
async def test_gcp_error_classification(status_code: int, error_type: type[Exception]) -> None:
    reranker = GcpReranker(
        project_id="project",
        access_token_provider=_token,
        http_client=_gcp_client(status_code),
    )

    with pytest.raises(error_type):
        await reranker.rerank(RerankRequest(query="query", documents=("document",)))


async def test_aws_adapter_uses_rerank_api_shape() -> None:
    client = _AwsClient()
    reranker = AwsReranker(region="ca-central-1", model="amazon.rerank-v1:0", client=client)

    await reranker.rerank(RerankRequest(query="query", documents=("one", "two"), top_n=1))

    assert client.request is not None
    assert client.request["queries"][0]["type"] == "TEXT"
    config = client.request["rerankingConfiguration"]["bedrockRerankingConfiguration"]
    assert config["numberOfResults"] == 1
    assert config["modelConfiguration"]["modelArn"].endswith("/amazon.rerank-v1:0")


@pytest.mark.parametrize(
    ("error_code", "error_type"),
    [
        ("AccessDeniedException", TerminalRerankerError),
        ("ValidationException", TerminalRerankerError),
        ("ThrottlingException", TransientRerankerError),
    ],
)
async def test_aws_error_classification(error_code: str, error_type: type[Exception]) -> None:
    reranker = AwsReranker(client=_AwsClient(error_code=error_code))

    with pytest.raises(error_type) as raised:
        await reranker.rerank(RerankRequest(query="query", documents=("document",)))

    assert raised.value.error_code == error_code


def test_qwen_adapter_module_imports_without_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "app.core.providers.qwen_local_reranker"
    sys.modules.pop(module_name, None)
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch" or name.startswith("transformers"):
            raise AssertionError(f"optional dependency imported eagerly: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.import_module(module_name)


def test_qwen_adapter_rejects_nonpositive_batch_size() -> None:
    from app.core.providers.qwen_local_reranker import QwenLocalReranker

    with pytest.raises(ValueError, match="batch_size must be positive"):
        QwenLocalReranker(model_id="fixture", batch_size=0)


@pytest.mark.gcp
async def test_gcp_reranker_live(integration_env: dict[str, str]) -> None:
    reranker = GcpReranker(
        project_id=integration_env["GCP_PROJECT_ID"],
        location=integration_env.get("GCP_RERANK_LOCATION", "global"),
        model=integration_env.get("GCP_RERANK_MODEL", "semantic-ranker-default-004"),
    )
    results = await reranker.rerank(
        RerankRequest(
            query="What is the capital of Uruguay?",
            documents=("Montevideo is the capital of Uruguay.", "Paris is in France."),
        )
    )
    assert results[0].index == 0


@pytest.mark.aws
@pytest.mark.timeout(180)
async def test_aws_reranker_live(integration_env: dict[str, str]) -> None:
    reranker = AwsReranker(
        region=integration_env.get("AWS_RERANK_REGION", "ca-central-1"),
        model=integration_env.get("AWS_RERANK_MODEL", "amazon.rerank-v1:0"),
        aws_access_key_id=integration_env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=integration_env["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=integration_env.get("AWS_SESSION_TOKEN"),
    )
    results = await reranker.rerank(
        RerankRequest(
            query="What is the capital of Uruguay?",
            documents=("Montevideo is the capital of Uruguay.", "Paris is in France."),
        )
    )
    assert results[0].index == 0


@pytest.mark.cuda
@pytest.mark.timeout(600)
async def test_qwen_reranker_live(integration_env: dict[str, str]) -> None:
    from app.core.providers.qwen_local_reranker import QwenLocalReranker

    reranker = QwenLocalReranker(
        model_id=integration_env.get("QWEN_MODEL_ID", "Qwen/Qwen3-Reranker-0.6B"),
        device=integration_env.get("QWEN_DEVICE", "cuda"),
    )
    results = await reranker.rerank(
        RerankRequest(
            query="What is the capital of Uruguay?",
            documents=("Montevideo is the capital of Uruguay.", "Paris is in France."),
        )
    )
    assert results[0].index == 0
