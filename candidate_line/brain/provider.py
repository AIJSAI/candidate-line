"""The brain behind one interface, with two implementations and an echo for the audio path.

Why two: DR-003's switch rule. Bedrock is the platform of record, but this account's Bedrock quota for the
5.5 models is zero today, so the same turn can run on the Anthropic Messages API until it opens, selected by
BRAIN_PROVIDER alone. Both return the same Reply, so the turn loop, the traces and the evals never know which.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from candidate_line.settings import Settings

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    text: str


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    provider: str
    model: str


class Brain(Protocol):
    name: str
    model: str

    def reply(self, system: str, messages: Sequence[Message], max_tokens: int = 200) -> Reply: ...


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class EchoBrain:
    """Says the caller's words back. The audio path (item 3) is proven with this before any model is in it."""

    name = "echo"
    model = "echo"

    def reply(self, system: str, messages: Sequence[Message], max_tokens: int = 200) -> Reply:
        last_user = next((m.text for m in reversed(messages) if m.role == "user"), "")
        return Reply(
            text=last_user,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            provider=self.name,
            model=self.model,
        )


class BedrockConverseBrain:
    """Bedrock's Converse API through boto3. The client is injectable so tests never touch the network."""

    name = "bedrock"

    def __init__(self, model_id: str, region: str, client: Any | None = None) -> None:
        self.model = model_id
        if client is None:
            import boto3  # imported here so the echo brain and the tests pay nothing for it

            client = boto3.client("bedrock-runtime", region_name=region)
        self._client = client

    def reply(self, system: str, messages: Sequence[Message], max_tokens: int = 200) -> Reply:
        start = time.perf_counter()
        response = self._client.converse(
            modelId=self.model,
            system=[{"text": system}],
            messages=[{"role": m.role, "content": [{"text": m.text}]} for m in messages],
            inferenceConfig={"maxTokens": max_tokens},
        )
        text = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
        usage = response["usage"]
        return Reply(
            text=text,
            input_tokens=int(usage["inputTokens"]),
            output_tokens=int(usage["outputTokens"]),
            latency_ms=_elapsed_ms(start),
            provider=self.name,
            model=self.model,
        )


# Haiku 5.5 thinks by default (its model card). A caller is waiting, so the live turn asks for no thinking and
# low effort; the first measured call (DR-003) decides whether that stays. Effort rides in output_config.
LOW_LATENCY_REQUEST: dict[str, Any] = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}


class AnthropicMessagesBrain:
    """The Anthropic Messages API through the official SDK, which reads ANTHROPIC_API_KEY from the environment."""

    name = "anthropic"

    def __init__(
        self, model_id: str, client: Any | None = None, request_overrides: dict[str, Any] | None = None
    ) -> None:
        self.model = model_id
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._overrides = LOW_LATENCY_REQUEST if request_overrides is None else request_overrides

    def reply(self, system: str, messages: Sequence[Message], max_tokens: int = 200) -> Reply:
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": m.role, "content": m.text} for m in messages],
            **self._overrides,
        )
        text = "".join(getattr(block, "text", "") for block in response.content)
        return Reply(
            text=text,
            input_tokens=int(response.usage.input_tokens),
            output_tokens=int(response.usage.output_tokens),
            latency_ms=_elapsed_ms(start),
            provider=self.name,
            model=self.model,
        )


def make_brain(settings: Settings) -> Brain:
    """One place where BRAIN_PROVIDER becomes an object; the switch rule in DR-003 is this function."""
    if settings.brain_provider == "bedrock":
        return BedrockConverseBrain(settings.bedrock_model_id, settings.aws_region)
    if settings.brain_provider == "anthropic":
        return AnthropicMessagesBrain(settings.anthropic_model_id)
    return EchoBrain()
