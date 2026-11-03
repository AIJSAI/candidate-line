from types import SimpleNamespace

from candidate_line.brain import (
    AnthropicMessagesBrain,
    BedrockConverseBrain,
    EchoBrain,
    Message,
    ToolCall,
    ToolResult,
    ToolSpec,
    make_brain,
)
from candidate_line.settings import Settings

SYSTEM = "You are Gus."
TURN = [Message("user", "Is the interview on Tuesday?")]


def test_echo_says_the_last_user_line_back() -> None:
    reply = EchoBrain().reply(SYSTEM, TURN)
    assert reply.text == "Is the interview on Tuesday?"
    assert reply.provider == "echo"


def test_make_brain_follows_the_provider_setting() -> None:
    assert make_brain(Settings.from_env({"BRAIN_PROVIDER": "echo"})).name == "echo"


class FakeBedrock:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def converse(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        if "toolConfig" in kwargs and not any(
            m["role"] == "user" and "toolResult" in m["content"][0] for m in kwargs["messages"]
        ):  # type: ignore[index]
            return {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"text": "One moment."},
                            {
                                "toolUse": {
                                    "toolUseId": "tu1",
                                    "name": "book_slot",
                                    "input": {"slot": "S1105-0930"},
                                }
                            },
                        ],
                    }
                },
                "usage": {"inputTokens": 20, "outputTokens": 9},
                "stopReason": "tool_use",
            }
        return {
            "output": {
                "message": {"role": "assistant", "content": [{"text": "Yes, "}, {"text": "Tuesday at ten."}]}
            },
            "usage": {"inputTokens": 13, "outputTokens": 4},
            "stopReason": "end_turn",
        }


def test_bedrock_brain_sends_converse_and_reads_usage() -> None:
    fake = FakeBedrock()
    brain = BedrockConverseBrain("us.anthropic.claude-haiku-5-5", "us-east-1", client=fake)
    reply = brain.reply(SYSTEM, TURN, max_tokens=50)
    assert reply.text == "Yes, Tuesday at ten."
    assert (reply.input_tokens, reply.output_tokens, reply.provider) == (13, 4, "bedrock")
    call = fake.calls[0]
    assert call["modelId"] == "us.anthropic.claude-haiku-5-5"
    assert call["system"] == [{"text": SYSTEM}]
    assert call["messages"] == [{"role": "user", "content": [{"text": TURN[0].text}]}]
    assert call["inferenceConfig"] == {"maxTokens": 50}


class FakeAnthropic:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if (
            "tools" in kwargs
            and kwargs["messages"][-1]["role"] == "user"
            and isinstance(kwargs["messages"][-1]["content"], str)
        ):  # type: ignore[index]
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="One moment."),
                    SimpleNamespace(
                        type="tool_use", id="tu1", name="book_slot", input={"slot": "S1105-0930"}
                    ),
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=12, cache_read_input_tokens=2048),
                stop_reason="tool_use",
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Tuesday at ten.")],
            usage=SimpleNamespace(input_tokens=11, output_tokens=5),
            stop_reason="end_turn",
        )


def test_anthropic_brain_asks_for_no_thinking_and_low_effort() -> None:
    fake = FakeAnthropic()
    reply = AnthropicMessagesBrain("claude-haiku-5-5", client=fake).reply(SYSTEM, TURN)
    assert reply.text == "Tuesday at ten."
    assert (reply.input_tokens, reply.output_tokens, reply.provider) == (11, 5, "anthropic")
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"] == [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user", "content": TURN[0].text}]
    assert call["thinking"] == {"type": "disabled"}
    assert call["output_config"] == {"effort": "low"}


BOOK = ToolSpec(
    "book_slot",
    "Books an open slot for the verified caller.",
    {"type": "object", "properties": {"slot": {"type": "string"}}, "required": ["slot"]},
)


def test_anthropic_brain_carries_tool_calls_out_and_tool_results_back() -> None:
    fake = FakeAnthropic()
    brain = AnthropicMessagesBrain("claude-haiku-5-5", client=fake)
    first = brain.reply(SYSTEM, [Message("user", "Book Thursday at nine thirty.")], tools=[BOOK])
    assert first.tool_calls == (ToolCall("tu1", "book_slot", {"slot": "S1105-0930"}),)
    assert (
        first.stop_reason == "tool_use" and first.text == "One moment." and first.cached_input_tokens == 2048
    )
    assert fake.calls[0]["tools"] == [
        {"name": "book_slot", "description": BOOK.description, "input_schema": BOOK.input_schema}
    ]
    history = [
        Message("user", "Book Thursday at nine thirty."),
        Message("assistant", first.text, tool_calls=first.tool_calls),
        Message("tool", tool_results=(ToolResult("tu1", '{"booked": "S1105-0930"}'),)),
    ]
    second = brain.reply(SYSTEM, history, tools=[BOOK])
    assert second.tool_calls == () and second.text == "Tuesday at ten."
    sent = fake.calls[1]["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "One moment."},
            {"type": "tool_use", "id": "tu1", "name": "book_slot", "input": {"slot": "S1105-0930"}},
        ],
    }
    assert sent[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": '{"booked": "S1105-0930"}'}],
    }


def test_bedrock_brain_carries_tool_calls_out_and_tool_results_back() -> None:
    fake = FakeBedrock()
    brain = BedrockConverseBrain("us.anthropic.claude-haiku-4-5", "us-east-1", client=fake)
    first = brain.reply(SYSTEM, [Message("user", "Book Thursday.")], tools=[BOOK])
    assert (
        first.tool_calls == (ToolCall("tu1", "book_slot", {"slot": "S1105-0930"}),)
        and first.stop_reason == "tool_use"
    )
    assert fake.calls[0]["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"] == {"json": BOOK.input_schema}
    history = [
        Message("user", "Book Thursday."),
        Message("assistant", first.text, tool_calls=first.tool_calls),
        Message("tool", tool_results=(ToolResult("tu1", "booked", is_error=False),)),
    ]
    second = brain.reply(SYSTEM, history, tools=[BOOK])
    assert second.tool_calls == ()
    sent = fake.calls[1]["messages"]
    assert sent[1]["content"][1] == {
        "toolUse": {"toolUseId": "tu1", "name": "book_slot", "input": {"slot": "S1105-0930"}}
    }
    assert sent[2] == {
        "role": "user",
        "content": [{"toolResult": {"toolUseId": "tu1", "content": [{"text": "booked"}]}}],
    }


def test_the_echo_brain_ignores_tools() -> None:
    reply = EchoBrain().reply(SYSTEM, TURN, tools=[BOOK])
    assert reply.tool_calls == () and reply.text == TURN[0].text
