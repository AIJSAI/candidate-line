from types import SimpleNamespace

from candidate_line.telephony.speech import Heard, heard_from_result


def test_a_final_carries_its_confidence_and_its_lag_from_the_end_of_speech() -> None:
    result = SimpleNamespace(
        is_partial=False,
        end_time=2.0,
        alternatives=[
            SimpleNamespace(
                transcript="my code is 4821",
                items=[
                    SimpleNamespace(confidence=0.9),
                    SimpleNamespace(confidence=0.7),
                    SimpleNamespace(confidence=None),
                ],
            )
        ],
    )
    heard = heard_from_result(result, now=12.35, stream_started_at=10.0)
    assert heard == Heard("my code is 4821", False, confidence=0.8, final_lag_ms=350)


def test_a_partial_carries_neither_and_a_final_without_a_clock_has_no_lag() -> None:
    partial = SimpleNamespace(
        is_partial=True, end_time=1.0, alternatives=[SimpleNamespace(transcript="my", items=[])]
    )
    assert heard_from_result(partial, now=5.0, stream_started_at=1.0) == Heard("my", True)
    final = SimpleNamespace(
        is_partial=False, end_time=1.0, alternatives=[SimpleNamespace(transcript="hi", items=None)]
    )
    assert heard_from_result(final, now=5.0, stream_started_at=None) == Heard("hi", False, None, None)
