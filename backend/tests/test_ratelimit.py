"""US-92: DB-backed rate limits on the sign-in endpoints."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import RateLimit
from app.security import ratelimit
from tests.test_sessions import T0, Env, env  # noqa: F401
from tests.test_signin import GOOGLE_ENV, Flow

BODY = {"code": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"}


def post_invite(client: TestClient, ip: str | None = None) -> Any:
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post("/auth/invite", json=BODY, headers=headers)


def test_ac_invite_endpoint_returns_429_with_retry_after_after_10_per_hour_per_ip(
    env: Env,  # noqa: F811
) -> None:
    client = env.app(**GOOGLE_ENV)
    assert [post_invite(client).status_code for _ in range(10)] == [400] * 10
    blocked = post_invite(client)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "rate_limited"}
    assert 1 <= int(blocked.headers["retry-after"]) <= 3600


def test_ac_limit_resets_in_the_next_window(env: Env) -> None:  # noqa: F811
    client = env.app(**GOOGLE_ENV)
    for _ in range(11):
        post_invite(client)
    assert post_invite(client).status_code == 429
    env.clock.now = T0 + timedelta(hours=1)
    assert post_invite(client).status_code == 400


def test_ac_retry_after_counts_down_to_the_window_end(env: Env) -> None:  # noqa: F811
    client = env.app(**GOOGLE_ENV)
    env.clock.now = T0 + timedelta(minutes=45)  # T0 is on the hour, window ends in 15 minutes
    for _ in range(11):
        response = post_invite(client)
    assert response.status_code == 429 and response.headers["retry-after"] == "900"


def test_ac_invite_endpoint_has_a_global_limit_of_50_per_hour(env: Env) -> None:  # noqa: F811
    client = env.app(trusted_proxy_count="1", **GOOGLE_ENV)
    statuses = [post_invite(client, f"10.0.{i // 250}.{i % 250}").status_code for i in range(51)]
    assert statuses[:50] == [400] * 50
    assert statuses[50] == 429


def test_ac_global_counter_is_not_burned_by_one_blocked_ip(env: Env) -> None:  # noqa: F811
    client = env.app(trusted_proxy_count="1", **GOOGLE_ENV)
    for _ in range(40):
        post_invite(client, "9.9.9.9")  # 10 pass, 30 are blocked per IP
    assert post_invite(client, "8.8.8.8").status_code == 400


def test_ac_sign_in_start_and_callback_are_limited_to_30_per_hour_per_ip(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    for _ in range(15):
        assert flow.client.get("/auth/google/start", follow_redirects=False).status_code == 302
        assert flow.client.get("/auth/google/callback", follow_redirects=False).status_code == 302
    for path in ("/auth/google/start", "/auth/google/callback"):
        blocked = flow.client.get(path, follow_redirects=False)
        assert blocked.status_code == 302
        assert blocked.headers["location"] == "http://localhost:5173/sign-in?error=rate_limited"


def test_ac_counters_use_hashed_keys_never_raw_ips(env: Env) -> None:  # noqa: F811
    client = env.app(trusted_proxy_count="1", **GOOGLE_ENV)
    post_invite(client, "203.0.113.77")
    keys = env.db.scalars(select(RateLimit.key_hash)).all()
    assert len(keys) == 2  # per-IP and global
    assert all(len(k) == 64 and "203.0.113.77" not in k for k in keys)
    assert all(set(k) <= set("0123456789abcdef") for k in keys)


def test_ac_forwarded_for_is_ignored_unless_proxies_are_trusted(env: Env) -> None:  # noqa: F811
    client = env.app(**GOOGLE_ENV)
    for i in range(10):
        post_invite(client, f"1.1.1.{i}")  # spoofing a new IP each time must not help
    assert post_invite(client, "2.2.2.2").status_code == 429


def test_ac_trusted_proxy_count_takes_the_nth_entry_from_the_right(env: Env) -> None:  # noqa: F811
    client = env.app(trusted_proxy_count="1", **GOOGLE_ENV)
    for i in range(10):
        post_invite(client, f"spoofed-{i}, 5.5.5.5")  # the proxy appended the real client last
    assert post_invite(client, "spoofed-new, 5.5.5.5").status_code == 429
    assert post_invite(client, "spoofed-new, 6.6.6.6").status_code == 400
    two = env.app(trusted_proxy_count="2", **GOOGLE_ENV)
    for i in range(10):
        post_invite(two, f"spoof-{i}, 7.7.7.7, 10.1.1.1")  # client, then one trusted proxy hop
    assert post_invite(two, "spoof-x, 7.7.7.7, 10.1.1.1").status_code == 429
    assert post_invite(two, "spoof-x, 7.7.7.8, 10.1.1.1").status_code == 400
    assert post_invite(two, "9.9.9.9").status_code == 400  # too few entries: socket address used


def test_ac_purge_removes_only_old_windows(env: Env) -> None:  # noqa: F811
    old = T0 - timedelta(days=2)
    env.db.add_all(
        [
            RateLimit(key_hash="a" * 64, window_start=old, count=3),
            RateLimit(key_hash="b" * 64, window_start=T0, count=1),
        ]
    )
    env.db.flush()
    assert ratelimit.purge_old(env.db, T0) == 1
    assert env.db.scalars(select(RateLimit.key_hash)).all() == ["b" * 64]
