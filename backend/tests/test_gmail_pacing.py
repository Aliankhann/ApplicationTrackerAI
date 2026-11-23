"""Quota-aware pacing and per-thread retries in the REST Gmail client (no network)."""

import uuid
from collections import Counter
from datetime import UTC, datetime

import httpx
import pytest

from app.providers.gmail import DraftRequest, GmailNotFound, GmailRateLimited
from app.providers.gmail.pacing import UNIT_COSTS, TokenBucket
from app.providers.gmail.rest import RETRY_CAP_SECONDS, THREAD_FETCH_ATTEMPTS, RestGmailClient
from app.providers.google.oidc import OidcConfig
from app.providers.google.tokens import AccessTokenCache, CachedAccessTokens
from tests.fake_gmail_api import REFRESH_TOKEN, FakeGmailApi
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TOKEN_URL
from tests.fixtures.gmail_threads import OWNER, build_threads

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
CONFIG = OidcConfig(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, "iss", "auth", TOKEN_URL, "jwks")
IDS = ["t-confirm", "t-interview", "t-reject", "t-sent"]


class FakeTime:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Limiter:
    """Wraps the fake API: answers 429 for a thread id `times` times before letting it through."""

    def __init__(self, api: FakeGmailApi, limited: dict[str, int], retry_after: str | None = None):
        self.api, self.limited, self.retry_after = api, dict(limited), retry_after
        self.thread_gets: Counter[str] = Counter()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/threads/" in path:
            thread_id = path.rsplit("/", 1)[1]
            self.thread_gets[thread_id] += 1
            if self.limited.get(thread_id, 0) > 0:
                self.limited[thread_id] -= 1
                headers = {"Retry-After": self.retry_after} if self.retry_after else {}
                return httpx.Response(429, json={}, headers=headers)
        return self.api.handler(request)


def make(
    api: FakeGmailApi,
    time_: FakeTime,
    limited: dict[str, int] | None = None,
    *,
    retry_after: str | None = None,
    rate: float = 100.0,
    jitter: float = 0.5,
) -> tuple[RestGmailClient, Limiter]:
    limiter = Limiter(api, limited or {}, retry_after)
    http = httpx.Client(transport=httpx.MockTransport(limiter))
    tokens = CachedAccessTokens(
        uuid.uuid4(), REFRESH_TOKEN, CONFIG, http, AccessTokenCache(), lambda: NOW
    )
    bucket = TokenBucket(rate, time_.clock, time_.sleep)
    client = RestGmailClient(
        tokens, http, bucket=bucket, sleep=time_.sleep, jitter=lambda: jitter, max_concurrency=2
    )
    return client, limiter


@pytest.fixture
def api() -> FakeGmailApi:
    return FakeGmailApi.from_metas(OWNER, build_threads(NOW))


def test_bucket_sustained_rate_never_exceeds_the_budget() -> None:
    time_ = FakeTime()
    bucket = TokenBucket(100, time_.clock, time_.sleep)
    for _ in range(100):
        bucket.acquire(10)
    # 1000 units at 100/s: the first 100 are the burst, so at least 9 seconds had to pass
    assert time_.now == pytest.approx(9.0)


def test_bucket_burst_is_bounded_by_one_second_of_budget() -> None:
    time_ = FakeTime()
    bucket = TokenBucket(100, time_.clock, time_.sleep)
    for _ in range(10):
        bucket.acquire(10)
    assert time_.sleeps == []  # exactly the burst: no waiting
    bucket.acquire(10)
    assert time_.sleeps == [pytest.approx(0.1)]


def test_bucket_refills_with_idle_time_up_to_capacity() -> None:
    time_ = FakeTime()
    bucket = TokenBucket(100, time_.clock, time_.sleep)
    bucket.acquire(100)
    time_.now += 50  # a long idle must not bank more than one second of budget
    bucket.acquire(100)
    bucket.acquire(10)
    assert time_.sleeps == [pytest.approx(0.1)]


def test_bucket_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucket(0)


def test_every_method_pays_its_own_unit_cost_before_sending(api: FakeGmailApi) -> None:
    client, _ = make(api, FakeTime(), rate=1000.0)
    charged: list[float] = []
    original = client._bucket.acquire

    def spy(cost: float) -> None:
        charged.append(cost)
        original(cost)

    client._bucket.acquire = spy  # type: ignore[method-assign]
    client.get_profile()
    client.list_threads("newer_than:30d")
    client.get_thread("t-confirm")
    client.list_history("100")
    client.create_draft(
        DraftRequest("t-interview", "<a@x>", "<a@x>", "Re: Hi", "Body", "to@x.test")
    )
    client.get_draft("d-1")
    names = ["profile.get", "threads.list", "threads.get", "history.list"]
    names += ["drafts.create", "drafts.get"]
    assert charged == [UNIT_COSTS[name] for name in names]
    assert UNIT_COSTS == {
        "threads.get": 10,
        "threads.list": 10,
        "history.list": 2,
        "profile.get": 1,
        "drafts.create": 10,
        "drafts.get": 5,
    }


def test_a_batch_fetch_is_paced_by_the_budget(api: FakeGmailApi) -> None:
    time_ = FakeTime()
    client, _ = make(api, time_, rate=20.0)  # two threads.get per second
    client.get_threads(IDS)
    # profile (1) + 4 x 10 units at 20/s with 20 of burst: well over a second must have passed
    assert time_.now >= 1.0


def test_only_rate_limited_threads_are_re_requested(api: FakeGmailApi) -> None:
    time_ = FakeTime()
    client, limiter = make(api, time_, {"t-reject": 2, "t-sent": 1})
    found = client.get_threads(IDS)
    assert [t.thread_id for t in found] == IDS  # order kept
    assert limiter.thread_gets == {
        "t-confirm": 1,
        "t-interview": 1,
        "t-reject": 3,
        "t-sent": 2,
    }
    assert client.rate_limit_hits == 3


def test_retry_after_is_honoured_and_capped(api: FakeGmailApi) -> None:
    time_ = FakeTime()
    client, _ = make(api, time_, {"t-reject": 1}, retry_after="3")
    client.get_threads(IDS)
    assert time_.sleeps.count(3.0) == 1
    time_ = FakeTime()
    client, _ = make(api, time_, {"t-reject": 1}, retry_after="500")
    client.get_threads(IDS)
    assert RETRY_CAP_SECONDS in time_.sleeps


@pytest.mark.parametrize("jitter", [0.0, 0.5, 0.999])
def test_backoff_without_retry_after_is_exponential_with_bounded_full_jitter(
    api: FakeGmailApi, jitter: float
) -> None:
    time_ = FakeTime()
    client, _ = make(api, time_, {"t-reject": 3}, jitter=jitter)
    client.get_threads(IDS)
    retries = [s for s in time_.sleeps if s >= 0.0][-3:]  # the retry sleeps come last
    assert retries == [
        pytest.approx(jitter * 1.0),
        pytest.approx(jitter * 2.0),
        pytest.approx(jitter * 4.0),
    ]
    assert all(0.0 <= s <= RETRY_CAP_SECONDS for s in retries)


def test_persistent_rate_limit_raises_with_the_threads_already_fetched(
    api: FakeGmailApi,
) -> None:
    time_ = FakeTime()
    client, limiter = make(api, time_, {"t-reject": 99})
    with pytest.raises(GmailRateLimited) as raised:
        client.get_threads(IDS)
    assert {t.thread_id for t in raised.value.fetched} == {"t-confirm", "t-interview", "t-sent"}
    assert limiter.thread_gets["t-reject"] == THREAD_FETCH_ATTEMPTS
    assert limiter.thread_gets["t-confirm"] == 1  # successes are never fetched again


def test_a_missing_thread_still_raises_not_found(api: FakeGmailApi) -> None:
    client, _ = make(api, FakeTime())
    with pytest.raises(GmailNotFound):
        client.get_threads(["t-confirm", "t-nope"])
