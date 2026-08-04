from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.settings import settings


def test_pytest_environment_is_hermetic() -> None:
    assert settings.__class__.model_config["env_file"] is None
    assert settings.app_env == "test"
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.provider == "stub"
    assert settings.fallback_provider is None
    assert settings.notion_mcp_enabled is False
    assert settings.notion_read_enabled is False
    assert settings.notion_write_enabled is False
    assert settings.web_read_enabled is False
    assert settings.rag_enabled is False
    assert settings.database_url_app is None
    assert settings.reranker_aws_region == "ca-central-1"
    assert settings.reranker_aws_model == "amazon.rerank-v1:0"
    assert settings.reranker_gcp_project is None
    assert settings.reranker_gcp_location == "global"
    assert settings.reranker_gcp_model == "semantic-ranker-default-004"
    assert settings.reranker_qwen_model_id is None
    assert settings.reranker_qwen_device == "cuda"
    assert settings.reranking_benchmark_gcp_enabled is False
    assert settings.reranking_benchmark_aws_enabled is False
    assert settings.reranking_benchmark_qwen_enabled is False
    assert settings.reranking_benchmark_gcp_call_budget == 0
    assert settings.reranking_benchmark_aws_pacing_s == 15.0


def test_exported_environment_cannot_override_test_settings() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "FALLBACK_PROVIDER": "bedrock",
            "ROUTING_POLICY": "heuristic",
            "ROUTING_SHADOW_MODE_ENABLED": "true",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(Path(__file__).resolve()),
            "-k",
            "test_pytest_environment_is_hermetic",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_pytest_timeout_guardrail_is_active(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.getini("timeout") == "60"
