from types import SimpleNamespace

from candidate_line.brain import AnthropicMessagesBrain, BedrockConverseBrain, EchoBrain, Message, make_brain
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
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "Yes, "}, {"text": "Tuesday at ten."}]}},
            "usage": {"inputTokens": 13, "outputTokens": 4},
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
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Tuesday at ten.")],
            usage=SimpleNamespace(input_tokens=11, output_tokens=5),
        )


def test_anthropic_brain_asks_for_no_thinking_and_low_effort() -> None:
    fake = FakeAnthropic()
    reply = AnthropicMessagesBrain("claude-haiku-5-5", client=fake).reply(SYSTEM, TURN)
    assert reply.text == "Tuesday at ten."
    assert (reply.input_tokens, reply.output_tokens, reply.provider) == (11, 5, "anthropic")
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"] == SYSTEM
    assert call["messages"] == [{"role": "user", "content": TURN[0].text}]
    assert call["thinking"] == {"type": "disabled"}
    assert call["output_config"] == {"effort": "low"}
