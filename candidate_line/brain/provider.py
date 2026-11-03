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

Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about one tool: its name, the one line it reads, and the JSON Schema of its input.
    Card 04 declares one per May and Must-ask-first line; the providers render it in their own shape."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model asked for a tool. The id goes back with the result so the model can match them."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str  # what the model reads back: JSON or a sentence, never audio, never a secret
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """One turn of the conversation. An assistant message may carry the tool calls it made; a "tool" message
    carries their results (rendered as a user turn by both APIs). Tool calls never travel as text, so a parser
    can never mistake one for speech (the dry run of card 04 on a text protocol read a caller's PIN aloud)."""

    role: Role
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    provider: str
    model: str
    tool_calls: tuple[ToolCall, ...] = ()  # non-empty means the turn is not over: run them and call again
    stop_reason: str = "end_turn"
    cached_input_tokens: int = (
        0  # input tokens read from the prompt cache (priced at a tenth of the input rate)
    )
    cache_write_input_tokens: int = (
        0  # input tokens written into the cache (priced at 1.25 times the input rate)
    )


class Brain(Protocol):
    name: str
    model: str

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply: ...


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class EchoBrain:
    """Says the caller's words back. The audio path (item 3) is proven with this before any model is in it."""

    name = "echo"
    model = "echo"

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply:
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

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply:
        start = time.perf_counter()
        request: dict[str, Any] = {
            "modelId": self.model,
            "system": [{"text": system}],
            "messages": _converse_messages(messages),
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if tools:
            request["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.input_schema},
                        }
                    }
                    for t in tools
                ]
            }
        response = self._client.converse(**request)
        blocks = response["output"]["message"]["content"]
        text = "".join(block.get("text", "") for block in blocks)
        calls = tuple(
            ToolCall(
                id=str(b["toolUse"]["toolUseId"]),
                name=str(b["toolUse"]["name"]),
                args=dict(b["toolUse"].get("input") or {}),
            )
            for b in blocks
            if "toolUse" in b
        )
        usage = response["usage"]
        return Reply(
            text=text,
            input_tokens=int(usage["inputTokens"]),
            output_tokens=int(usage["outputTokens"]),
            latency_ms=_elapsed_ms(start),
            provider=self.name,
            model=self.model,
            tool_calls=calls,
            stop_reason=str(response.get("stopReason", "end_turn")),
            cached_input_tokens=int(usage.get("cacheReadInputTokens") or 0),
            cache_write_input_tokens=int(usage.get("cacheWriteInputTokens") or 0),
        )


def _converse_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """The Converse API's shape: a tool result is a user turn of toolResult blocks; a call is a toolUse block."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": r.call_id,
                                "content": [{"text": r.content}],
                                **({"status": "error"} if r.is_error else {}),
                            }
                        }
                        for r in m.tool_results
                    ],
                }
            )
            continue
        content: list[dict[str, Any]] = [{"text": m.text}] if m.text else []
        content += [{"toolUse": {"toolUseId": c.id, "name": c.name, "input": c.args}} for c in m.tool_calls]
        out.append({"role": m.role, "content": content})
    return out


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

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply:
        start = time.perf_counter()
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            # The system prompt is marked for the prompt cache: the persona and the FAQ are the same on every turn
            # of every call, and a tool turn resends them. Below the model's minimum cacheable size the mark is a
            # no-op; above it the usage reports cached input tokens, which the cost line carries.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": _anthropic_messages(messages),
            **self._overrides,
        }
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
            ]
        response = self._client.messages.create(**request)
        text = "".join(
            getattr(block, "text", "") for block in response.content if _block_type(block) == "text"
        )
        calls = tuple(
            ToolCall(id=str(block.id), name=str(block.name), args=dict(block.input or {}))
            for block in response.content
            if _block_type(block) == "tool_use"
        )
        return Reply(
            text=text,
            input_tokens=int(response.usage.input_tokens),
            output_tokens=int(response.usage.output_tokens),
            latency_ms=_elapsed_ms(start),
            provider=self.name,
            model=self.model,
            tool_calls=calls,
            stop_reason=str(getattr(response, "stop_reason", None) or "end_turn"),
            cached_input_tokens=int(getattr(response.usage, "cache_read_input_tokens", None) or 0),
            cache_write_input_tokens=int(getattr(response.usage, "cache_creation_input_tokens", None) or 0),
        )


def _block_type(block: Any) -> str:
    return str(getattr(block, "type", "text"))


def _anthropic_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """The Messages API's shape: a tool result is a user turn of tool_result blocks; a call is a tool_use block."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            **({"is_error": True} if r.is_error else {}),
                        }
                        for r in m.tool_results
                    ],
                }
            )
        elif m.tool_calls:
            content: list[dict[str, Any]] = [{"type": "text", "text": m.text}] if m.text else []
            content += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in m.tool_calls
            ]
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": m.role, "content": m.text})
    return out


def make_brain(settings: Settings) -> Brain:
    """One place where BRAIN_PROVIDER becomes an object; the switch rule in DR-003 is this function."""
    if settings.brain_provider == "bedrock":
        return BedrockConverseBrain(settings.bedrock_model_id, settings.aws_region)
    if settings.brain_provider == "anthropic":
        return AnthropicMessagesBrain(settings.anthropic_model_id)
    return EchoBrain()
