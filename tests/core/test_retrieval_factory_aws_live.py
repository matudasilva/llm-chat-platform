"""ORQ-23 Task 7: opt-in live contract check for the production reranker
wiring's new default region (us-west-2 -- Design decision 1). Same
convention as ORQ-22's live tests (`integration_env` fixture, credentials
captured before the hermetic settings scrub in tests/conftest.py) -- `aws`
marker, skipped unless RUN_AWS_RERANK_INTEGRATION is set. A single call to
respect the account-wide Bedrock Rerank pacing found in ORQ-22
(docs/reranking_benchmark.md).
"""

from __future__ import annotations

import pytest

from app.core.domain.reranker import RerankRequest
from app.core.providers.aws_reranker import AwsReranker

pytestmark = pytest.mark.aws


@pytest.mark.asyncio
async def test_production_reranker_region_reaches_aws(integration_env: dict[str, str]) -> None:
    reranker = AwsReranker(
        region=integration_env.get("AWS_RERANK_REGION", "us-west-2"),
        model=integration_env.get("AWS_RERANK_MODEL", "amazon.rerank-v1:0"),
        aws_access_key_id=integration_env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=integration_env["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=integration_env.get("AWS_SESSION_TOKEN"),
    )
    result = await reranker.rerank(
        RerankRequest(
            query="what is retrieval augmented generation",
            documents=[
                "Retrieval augmented generation combines a retriever with a generator.",
                "The weather today is sunny with a light breeze.",
            ],
            top_n=2,
        )
    )
    assert len(result) == 2
    assert {r.index for r in result} == {0, 1}
