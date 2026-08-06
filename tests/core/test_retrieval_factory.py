"""ORQ-23/24: hermetic wiring tests for build_reranker()/build_embedding_provider()
-- the settings singleton is always blanked to hermetic defaults inside
pytest (tests/conftest.py), so these check field pass-through with a fake
settings object rather than a real AWS/GCP/OpenAI call (see
test_retrieval_factory_aws_live.py and test_reranker_adapters.py::
test_gcp_reranker_live for the opt-in live checks -- the latter, from
ORQ-22, already exercises GcpReranker against real ADC credentials and
satisfies ORQ-24 spec.md's AC8).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.domain.retrieval_factory import build_embedding_provider, build_reranker
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.cascading_reranker import CascadingRerankerAdapter
from app.core.providers.gcp_reranker import GcpReranker
from app.core.providers.openai_embedding_provider import OpenAIEmbeddingProvider


def _fake_settings(**overrides):
    defaults = dict(
        reranker_aws_region="us-west-2",
        reranker_aws_model="amazon.rerank-v1:0",
        aws_access_key_id="AKIA_TEST",
        aws_secret_access_key="secret",
        aws_session_token=None,
        reranker_gcp_project="my-gcp-project",
        reranker_gcp_location="global",
        reranker_gcp_model="semantic-ranker-default-004",
        openai_api_key="sk-test",
        rag_embedding_dimensions=1536,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_reranker_wires_gcp_primary_aws_fallback_cascade():
    reranker = build_reranker(_fake_settings())

    assert isinstance(reranker, CascadingRerankerAdapter)
    assert isinstance(reranker._primary, GcpReranker)
    assert isinstance(reranker._fallback, AwsReranker)
    assert reranker._primary._project_id == "my-gcp-project"
    assert reranker._primary._location == "global"
    assert reranker._primary._model == "semantic-ranker-default-004"
    assert reranker._fallback._region == "us-west-2"
    assert reranker._fallback._model == "amazon.rerank-v1:0"
    assert reranker._fallback._credentials["aws_access_key_id"] == "AKIA_TEST"


def test_build_embedding_provider_wires_openai_settings():
    provider = build_embedding_provider(_fake_settings())

    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_build_embedding_provider_requires_api_key():
    with pytest.raises(RuntimeError):
        build_embedding_provider(_fake_settings(openai_api_key=None))
