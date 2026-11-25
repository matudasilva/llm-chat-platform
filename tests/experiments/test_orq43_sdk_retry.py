"""Offline botocore retry behavior; no provider or network is contacted."""


import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.config import Config
from botocore.exceptions import ClientError


class _RawBody:
    def __init__(self, body):
        self._body = body

    def stream(self, amt=None, decode_content=False):
        yield self._body


@pytest.mark.parametrize("attempts", [1, 2])
def test_bedrock_sdk_counts_physical_attempts_on_retryable_response(monkeypatch, attempts):
    """Count sends on the real SDK retry path, including a retrying control."""
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        endpoint_url="https://offline.invalid",
        aws_access_key_id="offline",
        aws_secret_access_key="offline",
        config=Config(retries={"total_max_attempts": attempts, "mode": "standard"}),
    )
    sends = []

    def send(request):
        sends.append(request)
        return AWSResponse(
            request.url,
            503,
            {"content-type": "application/json", "x-amzn-errortype": "ServiceUnavailableException"},
            _RawBody(b'{"message":"offline synthetic failure"}'),
        )

    monkeypatch.setattr(client._endpoint.http_session, "send", send)
    monkeypatch.setattr("botocore.endpoint.time.sleep", lambda _: None)
    with pytest.raises(ClientError) as exc:
        client.converse(modelId="offline-model", messages=[{"role": "user", "content": [{"text": "hello"}]}])

    assert exc.value.response["Error"]["Code"] == "ServiceUnavailableException"
    assert len(sends) == attempts
