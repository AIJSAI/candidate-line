"""The calling window and the attempts, as pure functions of the time they are given (spec 9.2 and 9.4).

Why pure: the window decides when a stranger's phone rings, so it is tested on a pinned clock across zones, days and
edges, with no file, network or wall clock in it. Every time is aware and is returned in UTC, the way the ledger
stamps dials; the window itself is read in the applicant's own zone. Sunday is never a calling day here, whatever
window is given, because a setting is parsed elsewhere and this module is the last word on the time a dial gets.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from candidate_line.settings import SUNDAY, CallWindow

# The first dial waits two minutes after intake, so an applicant who has just pressed send is off the careers page
# before the phone rings; the second attempt is two hours after the first (spec 9.4).
FIRST_DIAL_AFTER = timedelta(seconds=120)
SECOND_ATTEMPT_AFTER = timedelta(hours=2)


def _zone(zone: str | ZoneInfo) -> ZoneInfo:
    return zone if isinstance(zone, ZoneInfo) else ZoneInfo(zone)


def _aware(at: datetime) -> datetime:
    if at.tzinfo is None:
        # A naive time would be read in the machine's zone, which on the task is UTC and on the Mac is Central.
        raise ValueError("a calling-window time must carry its zone")
    return at


def is_calling_day(window: CallWindow, weekday: int) -> bool:
    return weekday != SUNDAY and weekday in window.days


def in_window(at: datetime, zone: str | ZoneInfo, window: CallWindow) -> bool:
    """True from the window's start up to, not including, its end, on a calling day, in the applicant's zone."""
    local = _aware(at).astimezone(_zone(zone))
    return is_calling_day(window, local.weekday()) and window.start <= local.time() < window.end


def _at(day: date, when: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, when, tzinfo=zone).astimezone(UTC)


def next_calling_day(window: CallWindow, after: date) -> date:
    """The first calling day after `after`. A week always holds one, since a window names at least one day."""
    for step in range(1, 8):
        day = after + timedelta(days=step)
        if is_calling_day(window, day.weekday()):
            return day
    raise ValueError("the calling window names no day but Sunday")


def next_in_window(at: datetime, zone: str | ZoneInfo, window: CallWindow) -> datetime:
    """`at` itself when it is inside the window, otherwise the window's next opening, in UTC."""
    z = _zone(zone)
    if in_window(at, z, window):
        return at.astimezone(UTC)
    local = at.astimezone(z)
    if is_calling_day(window, local.weekday()) and local.time() < window.start:
        return _at(local.date(), window.start, z)
    return _at(next_calling_day(window, local.date()), window.start, z)


def first_dial_at(received: datetime, zone: str | ZoneInfo, window: CallWindow) -> datetime:
    """When intake schedules attempt 1: two minutes after the application, or the window's next opening."""
    return next_in_window(_aware(received) + FIRST_DIAL_AFTER, zone, window)


def next_attempt(
    attempt_made: int, made_at: datetime, zone: str | ZoneInfo, window: CallWindow, max_attempts: int
) -> datetime | None:
    """When the attempt after `attempt_made` is due, or None when no attempt is left. Attempt 2 is two hours after
    the first, moved into the window; attempt 3 is the next calling day at the window's middle (spec 9.4)."""
    following = attempt_made + 1
    if following > max_attempts or following > 3:
        return None
    z = _zone(zone)
    if following == 2:
        return next_in_window(_aware(made_at) + SECOND_ATTEMPT_AFTER, z, window)
    local_day = _aware(made_at).astimezone(z).date()
    return _at(next_calling_day(window, local_day), window.middle, z)
