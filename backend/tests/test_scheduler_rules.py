"""US-63: scheduler rules as property tests with a fake clock (instants are injected)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from app.providers.gmail.types import MessageMeta, ThreadMeta
from app.services.classification import ApplicationStatus
from app.services.followup_policy import (
    DAILY_DRAFT_CAP,
    Decision,
    StopReason,
    decide,
    due_at_for,
    in_send_window,
    local_day_bounds,
    local_to_utc,
    next_window_start,
    should_stop,
)

ZONES = [
    ZoneInfo(n)
    for n in (
        "America/Toronto",
        "Europe/London",
        "Asia/Kolkata",
        "Australia/Lord_Howe",
        "Pacific/Chatham",
        "UTC",
    )
]
zones = st.sampled_from(ZONES)
instants = st.datetimes(
    min_value=datetime(2023, 1, 1), max_value=datetime(2028, 12, 31), timezones=st.just(UTC)
)
BASE = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


def _msg(
    i: int, *, user: bool, labels: set[str] | None = None, at: datetime | None = None
) -> MessageMeta:
    return MessageMeta(
        message_id=f"m{i}",
        thread_id="t",
        from_address="x@example.com",
        from_name="",
        subject="s",
        snippet="",
        sent_at=at or BASE + timedelta(hours=i),
        from_user=user,
        rfc822_message_id=f"<{i}@x>",
        label_ids=frozenset(labels if labels is not None else {"SENT" if user else "INBOX"}),
    )


def _thread(*messages: MessageMeta) -> ThreadMeta:
    return ThreadMeta("t", "1", tuple(messages))


def _stop(
    thread: ThreadMeta,
    *,
    app_status: ApplicationStatus = ApplicationStatus.APPLIED,
    since: datetime = BASE,
    paused: bool = False,
    attempts: int = 0,
    gmail_revoked: bool = False,
) -> StopReason | None:
    return should_stop(
        app_status,
        thread,
        since=since,
        paused=paused,
        attempts=attempts,
        max_attempts=2,
        gmail_revoked=gmail_revoked,
    )


# AC1
@given(now=instants, tz=zones, drafted=st.integers(0, 10))
def test_ac1_never_drafts_outside_the_window(now: datetime, tz: ZoneInfo, drafted: int) -> None:
    if decide(now, tz, drafted, DAILY_DRAFT_CAP) is Decision.DRAFT:
        assert in_send_window(now, tz)
        local = now.astimezone(tz)
        assert local.weekday() < 5 and time(9) <= local.time() < time(11)


# AC2
@given(now=instants, tz=zones)
def test_ac2_next_window_start_is_minimal_and_inside(now: datetime, tz: ZoneInfo) -> None:
    start = next_window_start(now, tz)
    assert start >= now and start.tzinfo is not None
    assert in_send_window(start, tz)
    if in_send_window(now, tz):
        assert start == now
        return
    assert not in_send_window(start - timedelta(microseconds=1), tz)
    probe = now
    while probe < start:
        assert not in_send_window(probe, tz)
        probe += timedelta(minutes=7)


# AC3
@given(applied=instants, days=st.integers(1, 60), tz=zones)
def test_ac3_due_at_lands_on_local_date_at_nine(applied: datetime, days: int, tz: ZoneInfo) -> None:
    due = due_at_for(applied, days, tz).astimezone(tz)
    assert due.date() == applied.astimezone(tz).date() + timedelta(days=days)
    assert due.time() == time(9)


def test_ac3_dst_gap_moves_forward_and_ambiguous_uses_first_occurrence() -> None:
    toronto = ZoneInfo("America/Toronto")
    gap = local_to_utc(date(2026, 3, 8), time(2, 30), toronto)  # does not exist
    assert gap.astimezone(toronto).replace(tzinfo=None) == datetime(2026, 3, 8, 3, 30)
    fold = local_to_utc(date(2026, 11, 1), time(1, 30), toronto)  # happens twice
    assert fold == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # the EDT one (fold=0)


def test_ac3_due_date_across_spring_forward_keeps_nine_local() -> None:
    toronto = ZoneInfo("America/Toronto")
    applied = datetime(2026, 3, 5, 15, 0, tzinfo=UTC)  # 7 days later is after the change
    assert due_at_for(applied, 7, toronto) == datetime(2026, 3, 12, 13, 0, tzinfo=UTC)
    assert due_at_for(applied, 1, toronto) == datetime(2026, 3, 6, 14, 0, tzinfo=UTC)


# AC4
@given(
    pattern=st.lists(st.sampled_from(["user", "inbound", "draft"]), min_size=1, max_size=8),
    tz_status=st.sampled_from(list(ApplicationStatus)[:2]),
)
def test_ac4_never_drafts_after_a_reply(pattern: list[str], tz_status: ApplicationStatus) -> None:
    messages = [
        _msg(i, user=kind != "inbound", labels={"DRAFT"} if kind == "draft" else None)
        for i, kind in enumerate(pattern)
    ]
    real = [(i, k) for i, k in enumerate(pattern) if k != "draft"]
    users = [i for i, k in real if k == "user"]
    last_user = users[-1] if users else -1
    replied = any(k == "inbound" and i > last_user for i, k in real)
    reason = _stop(_thread(*messages), app_status=tz_status, since=BASE + timedelta(days=99))
    assert (reason is StopReason.REPLY_RECEIVED) == replied


# AC5
@given(
    tz=zones,
    cap=st.integers(1, 6),
    times=st.lists(instants, min_size=0, max_size=60),
)
@settings(max_examples=60)
def test_ac5_never_exceeds_daily_cap(tz: ZoneInfo, cap: int, times: list[datetime]) -> None:
    drafted: dict[date, int] = {}
    for now in sorted(times):
        day = now.astimezone(tz).date()
        if decide(now, tz, drafted.get(day, 0), cap) is Decision.DRAFT:
            drafted[day] = drafted.get(day, 0) + 1
    assert all(n <= cap for n in drafted.values())


def test_ac5_local_day_bounds_cover_the_local_day_across_dst() -> None:
    toronto = ZoneInfo("America/Toronto")
    start, end = local_day_bounds(datetime(2026, 3, 8, 18, 0, tzinfo=UTC), toronto)
    assert end - start == timedelta(hours=23)
    assert start == datetime(2026, 3, 8, 5, 0, tzinfo=UTC)


# AC6
@given(drafts=st.integers(1, 4), later=st.booleans())
def test_ac6_trailing_drafts_never_count_as_users_last_sent(drafts: int, later: bool) -> None:
    sent = _msg(0, user=True, at=BASE - timedelta(days=8))
    trailing = [_msg(i, user=True, labels={"DRAFT"}) for i in range(1, drafts + 1)]
    thread = _thread(sent, *trailing)
    assert _stop(thread, since=BASE) is None  # drafts are neither sent nor replies
    if later:
        thread = _thread(sent, _msg(9, user=False, at=BASE - timedelta(days=7)), *trailing)
        assert _stop(thread) is StopReason.REPLY_RECEIVED


# Other stop codes
def test_stop_codes_and_precedence() -> None:
    sent = _msg(0, user=True, at=BASE - timedelta(days=8))
    thread = _thread(sent)
    assert _stop(thread) is None
    assert _stop(thread, gmail_revoked=True) is StopReason.GMAIL_DISCONNECTED
    assert _stop(thread, paused=True) is StopReason.PAUSED
    assert _stop(thread, attempts=2) is StopReason.MAX_ATTEMPTS
    for status in (
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
    ):
        assert _stop(thread, app_status=status) is StopReason.STATUS_ADVANCED
    manual = _thread(sent, _msg(1, user=True, at=BASE + timedelta(minutes=1)))
    assert _stop(manual) is StopReason.USER_ALREADY_SENT
    assert _stop(_thread(sent, _msg(1, user=True, at=BASE))) is None  # not newer than `since`


# Daily mode: the job runs once a day, so any local weekday works at run time.
@given(now=instants, tz=zones, drafted=st.integers(0, 10))
def test_daily_mode_drafts_on_local_weekdays_only_and_never_over_the_cap(
    now: datetime, tz: ZoneInfo, drafted: int
) -> None:
    decision = decide(now, tz, drafted, DAILY_DRAFT_CAP, "daily")
    weekday = now.astimezone(tz).weekday() < 5
    assert (decision is Decision.DRAFT) == (weekday and drafted < DAILY_DRAFT_CAP)
    assert in_send_window(now, tz, "daily") == weekday


@given(now=instants, tz=zones)
def test_daily_mode_is_a_superset_of_the_window_and_window_mode_is_unchanged(
    now: datetime, tz: ZoneInfo
) -> None:
    if in_send_window(now, tz, "window"):
        assert in_send_window(now, tz, "daily")
    assert in_send_window(now, tz) == in_send_window(now, tz, "window")


@given(tz=zones, cap=st.integers(1, 6), times=st.lists(instants, max_size=60))
@settings(max_examples=60)
def test_daily_mode_never_exceeds_the_daily_cap_and_never_drafts_on_weekends(
    tz: ZoneInfo, cap: int, times: list[datetime]
) -> None:
    drafted: dict[date, int] = {}
    for now in sorted(times):
        day = now.astimezone(tz).date()
        if decide(now, tz, drafted.get(day, 0), cap, "daily") is Decision.DRAFT:
            assert day.weekday() < 5
            drafted[day] = drafted.get(day, 0) + 1
    assert all(n <= cap for n in drafted.values())


def test_daily_mode_due_time_is_start_of_the_local_day_so_that_days_run_picks_it_up() -> None:
    toronto = ZoneInfo("America/Toronto")
    applied = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
    due = due_at_for(applied, 7, toronto, "daily")
    assert due.astimezone(toronto).replace(tzinfo=None) == datetime(2026, 3, 9, 0, 0)
    run_at = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)  # 08:00 local that day
    assert due <= run_at
    assert due_at_for(applied, 7, toronto) == datetime(
        2026, 3, 9, 13, 0, tzinfo=UTC
    )  # window: 9:00


def test_daily_mode_replies_still_stop_followups() -> None:
    reply = _thread(_msg(0, user=True), _msg(1, user=False))
    assert _stop(reply, since=BASE - timedelta(days=1)) is StopReason.REPLY_RECEIVED
