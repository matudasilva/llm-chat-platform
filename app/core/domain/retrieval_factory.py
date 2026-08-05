from __future__ import annotations

from app.core.domain.embedding import EmbeddingPort
from app.core.domain.reranker import RerankerPort
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.openai_embedding_provider import (
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)
from app.core.settings import settings as default_settings


def build_reranker(cfg=None) -> RerankerPort:
    """
    Production reranker for the retrieval pipeline (ORQ-23 spec.md §Design
    decisions 1/6): the AWS adapter ORQ-22 already built, with the
    already-production-usable `reranker_aws_*` settings -- not the
    `reranking_benchmark_*` toggles, which stay ORQ-22-only.
    """
    cfg = cfg or default_settings
    return AwsReranker(
        region=cfg.reranker_aws_region,
        model=cfg.reranker_aws_model,
        aws_access_key_id=cfg.aws_access_key_id,
        aws_secret_access_key=cfg.aws_secret_access_key,
        aws_session_token=cfg.aws_session_token,
    )


def build_embedding_provider(cfg=None) -> EmbeddingPort:
    """
    Same embedding configuration as offline ingestion (ADR-006 §1): kept as
    an independent builder rather than importing app/scripts/ingest_corpus.py
    (a script module, not a shared library) or refactoring its private
    helper -- both out of this ORQ's scope.
    """
    cfg = cfg or default_settings
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the retrieval pipeline")
    return OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=cfg.openai_api_key,
            dimensions=cfg.rag_embedding_dimensions,
        )
    )
