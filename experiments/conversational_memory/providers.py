from __future__ import annotations

from typing import Any

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import messages_for_provider
from app.core.providers.openai_provider import OpenAIProvider


class ConversationExperimentOpenAIProvider(OpenAIProvider):
    """Experiment-only Responses adapter for multi-message transcript replay.

    The production adapter currently encodes every role's content item as
    ``input_text``. The Responses API rejected the first replay containing an
    assistant message with HTTP 400. Its documented input-message contract also
    accepts string content for user, assistant, system, and developer roles, so
    Gate 1 uses that neutral representation without changing production code.
    """

    def _build_payload(self, input: ProviderInput) -> dict[str, Any]:
        messages = messages_for_provider(input)
        return {
            "model": self._cfg.model,
            "input": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
