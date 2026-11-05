"""The calling window and the attempts on a pinned clock (spec 9.2 and 9.4, DR-025 sections 11 and 17)."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from candidate_line.outbound.window import (
    first_dial_at,
    in_window,
    next_attempt,
    next_in_window,
)
from candidate_line.settings import CallWindow, parse_call_window

WINDOW = parse_call_window("09:00-20:00 Mon-Sat")
ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
# Thursday 5 November 2026; Saturday is the 7th, Sunday the 8th, Monday the 9th.
THURSDAY, SATURDAY, SUNDAY, MONDAY = 5, 7, 8, 9


def local(zone: str, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=ZoneInfo(zone))


@pytest.mark.parametrize("zone", ZONES)
def test_inside_and_outside_the_window_in_each_zone(zone: str) -> None:
    assert in_window(local(zone, THURSDAY, 12), zone, WINDOW)
    assert not in_window(local(zone, THURSDAY, 7), zone, WINDOW)
    assert not in_window(local(zone, THURSDAY, 21), zone, WINDOW)
    assert not in_window(local(zone, SUNDAY, 12), zone, WINDOW)
    assert in_window(local(zone, SATURDAY, 12), zone, WINDOW)


@pytest.mark.parametrize("zone", ZONES)
def test_the_windows_edges_start_inside_and_end_outside(zone: str) -> None:
    assert in_window(local(zone, THURSDAY, 9, 0, 0), zone, WINDOW)
    assert not in_window(local(zone, THURSDAY, 8, 59, 59), zone, WINDOW)
    assert in_window(local(zone, THURSDAY, 19, 59, 59), zone, WINDOW)
    assert not in_window(local(zone, THURSDAY, 20, 0, 0), zone, WINDOW)


def test_the_same_instant_is_inside_one_zone_and_outside_another() -> None:
    # 14:30 UTC on a Thursday: 09:30 in New York, 06:30 in Los Angeles.
    at = datetime(2026, 11, 5, 14, 30, tzinfo=UTC)
    assert in_window(at, "America/New_York", WINDOW)
    assert not in_window(at, "America/Los_Angeles", WINDOW)
    assert next_in_window(at, "America/Los_Angeles", WINDOW) == local("America/Los_Angeles", THURSDAY, 9)


@pytest.mark.parametrize("zone", ZONES)
def test_next_in_window_keeps_an_inside_time_and_moves_an_outside_one_to_the_next_opening(zone: str) -> None:
    inside = local(zone, THURSDAY, 15, 7)
    assert next_in_window(inside, zone, WINDOW) == inside
    assert next_in_window(inside, zone, WINDOW).tzinfo == UTC
    assert next_in_window(local(zone, THURSDAY, 6), zone, WINDOW) == local(zone, THURSDAY, 9)
    assert next_in_window(local(zone, THURSDAY, 20), zone, WINDOW) == local(zone, 6, 9)
    assert next_in_window(local(zone, SATURDAY, 20, 30), zone, WINDOW) == local(zone, MONDAY, 9)
    assert next_in_window(local(zone, SUNDAY, 12), zone, WINDOW) == local(zone, MONDAY, 9)


@pytest.mark.parametrize("zone", ZONES)
def test_no_sunday_time_is_ever_returned_across_a_whole_week(zone: str) -> None:
    z = ZoneInfo(zone)
    start = datetime(2026, 11, 2, 0, 0, tzinfo=z)  # a Monday
    for step in range(0, 7 * 24 * 60, 17):
        at = start + timedelta(minutes=step)
        due = next_in_window(at, zone, WINDOW)
        assert due >= at
        assert in_window(due, zone, WINDOW)
        assert due.astimezone(z).weekday() != 6
        for attempt in (1, 2):
            following = next_attempt(attempt, at, zone, WINDOW, 3)
            assert following is not None and following.astimezone(z).weekday() != 6
            assert in_window(following, zone, WINDOW)


def test_a_window_built_with_sunday_in_it_still_never_returns_a_sunday() -> None:
    # The settings refuse such a window; this module holds the line even when it is handed one.
    every_day = CallWindow(time(9, 0), time(20, 0), frozenset(range(7)))
    saturday_night = local("America/Chicago", SATURDAY, 21)
    assert next_in_window(saturday_night, "America/Chicago", every_day) == local("America/Chicago", MONDAY, 9)
    assert not in_window(local("America/Chicago", SUNDAY, 12), "America/Chicago", every_day)


def test_the_first_dial_is_two_minutes_after_intake_or_at_the_next_opening() -> None:
    zone = "America/Chicago"
    assert first_dial_at(local(zone, THURSDAY, 10), zone, WINDOW) == local(zone, THURSDAY, 10, 2)
    assert first_dial_at(local(zone, THURSDAY, 19, 59), zone, WINDOW) == local(zone, 6, 9)
    assert first_dial_at(local(zone, SATURDAY, 22), zone, WINDOW) == local(zone, MONDAY, 9)


@pytest.mark.parametrize("zone", ZONES)
def test_attempt_two_is_two_hours_later_moved_into_the_window(zone: str) -> None:
    assert next_attempt(1, local(zone, THURSDAY, 10), zone, WINDOW, 3) == local(zone, THURSDAY, 12)
    assert next_attempt(1, local(zone, THURSDAY, 18, 30), zone, WINDOW, 3) == local(zone, 6, 9)
    # A Saturday 19:59 miss would be 21:59 Saturday; Sunday is never a calling day, so it moves to Monday.
    assert next_attempt(1, local(zone, SATURDAY, 19, 59), zone, WINDOW, 3) == local(zone, MONDAY, 9)


@pytest.mark.parametrize("zone", ZONES)
def test_attempt_three_is_the_next_calling_day_at_the_windows_middle(zone: str) -> None:
    assert WINDOW.middle == time(14, 30)
    assert next_attempt(2, local(zone, THURSDAY, 12), zone, WINDOW, 3) == local(zone, 6, 14, 30)
    assert next_attempt(2, local(zone, SATURDAY, 9), zone, WINDOW, 3) == local(zone, MONDAY, 14, 30)


def test_no_attempt_past_max_dial_attempts() -> None:
    zone = "America/Chicago"
    at = local(zone, THURSDAY, 10)
    assert next_attempt(3, at, zone, WINDOW, 3) is None
    assert next_attempt(1, at, zone, WINDOW, 1) is None
    assert next_attempt(2, at, zone, WINDOW, 2) is None
    assert next_attempt(1, at, zone, WINDOW, 2) is not None


def test_a_time_without_its_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="zone"):
        in_window(datetime(2026, 11, 5, 12, 0), "America/Chicago", WINDOW)


def test_the_window_holds_across_the_daylight_saving_change() -> None:
    # Sunday 1 November 2026 is the fall-back day; Saturday evening's miss is due on Monday at 09:00 local.
    zone = "America/New_York"
    due = next_attempt(1, datetime(2026, 10, 31, 19, 30, tzinfo=ZoneInfo(zone)), zone, WINDOW, 3)
    assert due == datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo(zone))
    assert due.astimezone(UTC).hour == 14  # EST is UTC-5 from the first
