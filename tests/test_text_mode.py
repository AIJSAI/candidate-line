from candidate_line.brain import EchoBrain
from candidate_line.hooks import NoHooks
from candidate_line.text_mode import repl


def test_repl_echoes_lines_and_handles_its_two_commands() -> None:
    out: list[str] = []
    repl(EchoBrain(), NoHooks(), ["hello", "", "/silence 7", "/quit", "never reached"], out.append)
    assert out[0].startswith("[echo echo] text mode")
    assert out[1] == "gus> hello"
    assert out[2].endswith("0 ms, 0 in, 0 out")
    assert out[3] == "(silence hook said nothing)"
    assert len(out) == 4
