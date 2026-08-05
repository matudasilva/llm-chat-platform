"""ORQ-23: hermetic wiring tests for build_reranker()/build_embedding_provider()
-- the settings singleton is always blanked to hermetic defaults inside
pytest (tests/conftest.py), so these check field pass-through with a fake
settings object rather than a real AWS/OpenAI call (see
test_retrieval_factory_aws_live.py for the opt-in live check).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.domain.retrieval_factory import build_embedding_provider, build_reranker
from app.core.providers.aws_reranker import AwsReranker
from app.core.providers.openai_embedding_provider import OpenAIEmbeddingProvider


def _fake_settings(**overrides):
    defaults = dict(
        reranker_aws_region="us-west-2",
        reranker_aws_model="amazon.rerank-v1:0",
        aws_access_key_id="AKIA_TEST",
        aws_secret_access_key="secret",
        aws_session_token=None,
        openai_api_key="sk-test",
        rag_embedding_dimensions=1536,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_reranker_wires_production_settings():
    reranker = build_reranker(_fake_settings())

    assert isinstance(reranker, AwsReranker)
    assert reranker._region == "us-west-2"
    assert reranker._model == "amazon.rerank-v1:0"
    assert reranker._credentials["aws_access_key_id"] == "AKIA_TEST"


def test_build_embedding_provider_wires_openai_settings():
    provider = build_embedding_provider(_fake_settings())

    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_build_embedding_provider_requires_api_key():
    with pytest.raises(RuntimeError):
        build_embedding_provider(_fake_settings(openai_api_key=None))
