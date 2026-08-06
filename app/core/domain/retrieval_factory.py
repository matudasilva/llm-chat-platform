from __future__ import annotations

from app.core.domain.embedding import EmbeddingPort
from app.core.domain.reranker import RerankerPort
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.cascading_reranker import CascadingRerankerAdapter
from app.core.providers.gcp_reranker import GcpReranker
from app.core.providers.openai_embedding_provider import (
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)
from app.core.settings import settings as default_settings


def build_reranker(cfg=None) -> RerankerPort:
    """
    Production reranker for the retrieval pipeline (ORQ-24 spec.md §Design
    decisions 1): a GCP-primary/AWS-fallback availability cascade.
    AWS Bedrock Rerank's account-level quota is a hard, non-adjustable
    2 requests/minute (aws_quota_finding.md); GCP is primary because ORQ-22's
    benchmark found no quality gap between backends. `reranker_gcp_*` and
    `reranker_aws_*` are both already production-usable settings -- not the
    `reranking_benchmark_*` toggles, which stay ORQ-22-only.
    """
    cfg = cfg or default_settings
    primary = GcpReranker(
        project_id=cfg.reranker_gcp_project or "",
        location=cfg.reranker_gcp_location,
        model=cfg.reranker_gcp_model,
    )
    fallback = AwsReranker(
        region=cfg.reranker_aws_region,
        model=cfg.reranker_aws_model,
        aws_access_key_id=cfg.aws_access_key_id,
        aws_secret_access_key=cfg.aws_secret_access_key,
        aws_session_token=cfg.aws_session_token,
    )
    return CascadingRerankerAdapter(primary=primary, fallback=fallback)


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
