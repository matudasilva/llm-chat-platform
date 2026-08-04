from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Awaitable, Callable
from urllib.parse import quote

import httpx

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)

_BACKEND = "gcp"
_DEFAULT_MODEL = "semantic-ranker-default-004"


class AdcAccessTokenProvider:
    """Minimal authorized-user ADC refresh over REST, without a Google SDK."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client
        self._token: str | None = None
        self._expires_at = 0.0

    async def __call__(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        credential_path = Path(path) if path else Path.home() / ".config/gcloud/application_default_credentials.json"
        try:
            credentials = json.loads(credential_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TerminalRerankerError("GCP ADC credentials are unavailable", backend=_BACKEND) from exc

        if credentials.get("type") != "authorized_user":
            raise TerminalRerankerError(
                "GCP ADC must use host-level authorized-user credentials",
                backend=_BACKEND,
            )

        required = ("client_id", "client_secret", "refresh_token")
        if any(not credentials.get(name) for name in required):
            raise TerminalRerankerError("GCP ADC credentials are incomplete", backend=_BACKEND)

        token_uri = credentials.get("token_uri", "https://oauth2.googleapis.com/token")
        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(
                token_uri,
                data={
                    "client_id": credentials["client_id"],
                    "client_secret": credentials["client_secret"],
                    "refresh_token": credentials["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
        except httpx.RequestError as exc:
            raise TransientRerankerError("GCP ADC token exchange failed", backend=_BACKEND) from exc
        finally:
            if self._http_client is None:
                await client.aclose()

        if response.status_code >= 500 or response.status_code == 429:
            raise TransientRerankerError(
                "GCP ADC token service is unavailable",
                backend=_BACKEND,
                error_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise TerminalRerankerError(
                "GCP ADC token exchange was rejected",
                backend=_BACKEND,
                error_code=str(response.status_code),
            )

        try:
            body = response.json()
            token = str(body["access_token"])
            expires_in = int(body.get("expires_in", 3600))
        except (KeyError, TypeError, ValueError) as exc:
            raise TerminalRerankerError("GCP ADC token response is invalid", backend=_BACKEND) from exc
        self._token = token
        self._expires_at = time.time() + expires_in
        return token


class GcpReranker(RerankerPort):
    def __init__(
        self,
        *,
        project_id: str,
        location: str = "global",
        model: str = _DEFAULT_MODEL,
        access_token_provider: Callable[[], Awaitable[str]] | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._model = model
        self._access_token_provider = access_token_provider or AdcAccessTokenProvider()
        self._http_client = http_client
        self._timeout_s = timeout_s

    async def rerank(self, request: RerankRequest) -> list[RankedDocument]:
        top_n = _validate_request(request, backend=_BACKEND)
        if not request.documents:
            return []
        if not self._project_id:
            raise TerminalRerankerError("GCP project is required", backend=_BACKEND)

        token = await self._access_token_provider()
        project = quote(self._project_id, safe="")
        location = quote(self._location, safe="")
        url = (
            "https://discoveryengine.googleapis.com/v1/projects/"
            f"{project}/locations/{location}/rankingConfigs/default_ranking_config:rank"
        )
        payload = {
            "model": self._model,
            "query": request.query,
            "records": [
                {"id": str(index), "content": document}
                for index, document in enumerate(request.documents)
            ],
            "topN": top_n,
            "ignoreRecordDetailsInResponse": True,
        }
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_s)
        try:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Goog-User-Project": self._project_id,
                },
            )
        except httpx.RequestError as exc:
            raise TransientRerankerError("GCP reranker transport failed", backend=_BACKEND) from exc
        finally:
            if self._http_client is None:
                await client.aclose()

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientRerankerError(
                "GCP reranker is temporarily unavailable",
                backend=_BACKEND,
                error_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise TerminalRerankerError(
                "GCP reranker request was rejected",
                backend=_BACKEND,
                error_code=str(response.status_code),
            )

        try:
            records = response.json()["records"]
            results = [
                RankedDocument(
                    index=int(record["id"]),
                    rank=rank,
                    relevance_score=float(record["score"]) if record.get("score") is not None else None,
                )
                for rank, record in enumerate(records, start=1)
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise TerminalRerankerError("GCP reranker response is invalid", backend=_BACKEND) from exc
        if any(result.index < 0 or result.index >= len(request.documents) for result in results):
            raise TerminalRerankerError("GCP reranker returned an invalid document index", backend=_BACKEND)
        return results


def _validate_request(request: RerankRequest, *, backend: str) -> int:
    if not request.query.strip():
        raise TerminalRerankerError("rerank query must not be empty", backend=backend)
    if len(request.documents) > 200:
        raise TerminalRerankerError("rerank request exceeds 200 documents", backend=backend)
    if any(not document.strip() for document in request.documents):
        raise TerminalRerankerError("rerank documents must not be empty", backend=backend)
    top_n = len(request.documents) if request.top_n is None else request.top_n
    if top_n < 0 or top_n > len(request.documents):
        raise TerminalRerankerError("top_n is outside the document range", backend=backend)
    return top_n
