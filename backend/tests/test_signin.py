"""US-11 / US-12: Google sign-in callback and the invite gate, against the local fake Google."""

import logging
import threading
import urllib.parse
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_oidc
from app.config import get_settings
from app.models import AuditLog, InviteCode, OAuthToken, User, UserSession
from app.providers.google.oidc import Identity
from app.repositories import invite_codes
from app.security.invite_codes import generate_code, hash_code
from app.services import signin
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, FakeGoogle
from tests.test_sessions import T0, Env, env  # noqa: F401

FRONTEND = "http://localhost:5173"
GOOGLE_ENV = {
    "google_client_id": CLIENT_ID,
    "google_client_secret": CLIENT_SECRET,
    "google_redirect_uri": REDIRECT_URI,
}
OLD = "old@example.test"
NEW = "new@example.test"


class Flow:
    """A browser plus fake Google: drives start -> consent -> callback."""

    def __init__(self, env: Env, **settings: str) -> None:  # noqa: F811
        self.env = env
        self.google = FakeGoogle()
        self.client = env.app(**{**GOOGLE_ENV, **settings})
        oidc, _ = self.google.oidc(clock=lambda: env.clock.now.timestamp())
        self.client.app.dependency_overrides[get_oidc] = lambda: oidc  # type: ignore[attr-defined]
        self.oidc = oidc

    def invite(self, email: str | None = None, **kw: Any) -> str:
        code = generate_code()
        expires = kw.get("expires_at", T0 + timedelta(days=7))
        invite_codes.create(self.env.db, hash_code(code), expires, email)
        return code

    def submit_code(self, code: str) -> Any:
        return self.client.post("/auth/invite", json={"code": code}, headers={"Origin": FRONTEND})

    def start(self) -> str:
        response = self.client.get("/auth/google/start", follow_redirects=False)
        assert response.status_code == 302
        return str(response.headers["location"])

    def callback(self, code: str, state: str | None) -> Any:
        params = {"code": code, **({"state": state} if state else {})}
        return self.client.get("/auth/google/callback", params=params, follow_redirects=False)

    def sign_in(self, email: str, sub: str = "sub-new", **overrides: Any) -> Any:
        url = self.start()
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
        code = self.google.issue_code(url, sub, email, **overrides)
        return self.callback(code, state)


def counts(db: Session) -> tuple[int, int, int, int, int]:
    def n(model: Any) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    used = db.scalar(select(func.count()).where(InviteCode.used_at.is_not(None))) or 0
    return n(User), n(UserSession), n(OAuthToken), n(AuditLog), used


def error_of(response: Any) -> str:
    assert response.status_code == 302
    location = urllib.parse.urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND}/sign-in"
    return str(urllib.parse.parse_qs(location.query)["error"][0])


def assert_rejected(env: Env, response: Any, error: str, before: tuple[int, ...]) -> None:  # noqa: F811
    assert error_of(response) == error
    assert counts(env.db) == before
    set_cookies = response.headers.get_list("set-cookie")
    assert not [h for h in set_cookies if h.startswith("tracker_session=") and "Max-Age=0" not in h]


def test_ac_start_redirects_to_google_with_state_pkce_nonce_and_only_sign_in_scopes(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    response = flow.client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    parts = urllib.parse.urlsplit(response.headers["location"])
    query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    assert parts.netloc == "accounts.google.com"
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256" and query["code_challenge"]
    assert query["state"] and query["nonce"] and query["access_type"] == "online"
    assert query["redirect_uri"] == REDIRECT_URI
    cookie = response.headers["set-cookie"].lower()
    assert "tracker_oauth=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "max-age=600" in cookie
    assert query["state"] not in cookie.split(";")[0].split("=")[1].split(".")[1]  # not in clear


def test_ac_flow_cookie_is_host_prefixed_and_secure_outside_local(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    prod = env.app(
        "prod",
        session_secret="s" * 40,
        api_base_url="https://api.example.test",
        frontend_origin="https://app.example.test",
        **GOOGLE_ENV,
    )
    prod.app.dependency_overrides[get_oidc] = lambda: flow.oidc  # type: ignore[attr-defined]
    response = prod.get("/auth/google/start", follow_redirects=False)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-tracker_oauth=") and "Secure" in cookie


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/auth/google/start"), ("GET", "/auth/google/callback"), ("POST", "/auth/invite")],
)
def test_ac_sign_in_routes_fail_closed_with_503_when_google_is_not_configured(
    env: Env,  # noqa: F811
    method: str,
    path: str,
) -> None:
    client = env.app()
    response = client.request(method, path, json={"code": "x"} if method == "POST" else None)
    assert response.status_code == 503
    assert response.json() == {"detail": "sign_in_unavailable"}
    assert client.get("/health").status_code == 200  # the app itself still runs


def test_ac_invite_code_plus_google_creates_user_session_audit_and_marks_code_used(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    code = flow.invite()
    assert flow.submit_code(code).status_code == 204
    assert counts(env.db)[4] == 0  # validating a code does not use it
    response = flow.sign_in(NEW, "sub-1")
    assert response.status_code == 302 and response.headers["location"] == f"{FRONTEND}/app"
    user = env.db.scalars(select(User).where(User.google_sub == "sub-1")).one()
    assert user.email == NEW
    invite = env.db.scalars(select(InviteCode)).one()
    assert invite.used_by_user_id == user.id and invite.used_at == T0
    logins = env.db.scalars(select(AuditLog).where(AuditLog.action == "login")).all()
    assert [row.user_id for row in logins] == [user.id]
    assert env.db.scalar(select(func.count()).select_from(OAuthToken)) == 0
    assert flow.client.get("/me").json()["email"] == NEW
    cookies = {c.name for c in flow.client.cookies.jar}
    assert "tracker_oauth" not in cookies and "tracker_invite" not in cookies


def test_ac_callback_response_sets_session_and_csrf_cookies_and_clears_flow_cookie(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    flow.submit_code(flow.invite())
    headers = flow.sign_in(NEW).headers.get_list("set-cookie")
    names = [h.split("=")[0] for h in headers]
    assert {"tracker_session", "tracker_csrf", "tracker_oauth", "tracker_invite"} <= set(names)
    assert "httponly" in next(h for h in headers if h.startswith("tracker_session")).lower()
    assert "Max-Age=0" in next(h for h in headers if h.startswith("tracker_oauth"))


def test_ac_missing_or_mismatched_state_is_rejected_and_writes_nothing(
    env: Env,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    flow = Flow(env)
    code = flow.invite()
    flow.submit_code(code)
    before = counts(env.db)
    caplog.set_level(logging.INFO)
    for state in (None, "wrong-state"):  # a failed callback burns the flow, so restart each time
        url = flow.start()
        auth = flow.google.issue_code(url, "sub-1", NEW)
        assert_rejected(env, flow.callback(auth, state), "sign_in_failed", before)
    reasons = [getattr(r, "error_code", None) for r in caplog.records]
    assert reasons.count("state_mismatch") == 2
    assert auth in flow.google.pending  # Google was never asked to exchange the code
    server_logs = " ".join(
        r.getMessage() + str(r.__dict__) for r in caplog.records if r.name.startswith("app")
    )  # the test client's own httpx log line is excluded
    assert all(secret not in server_logs for secret in (auth, code, NEW, CLIENT_SECRET))


def test_ac_missing_expired_or_tampered_flow_cookie_is_rejected(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.submit_code(flow.invite())
    before = counts(env.db)
    url = flow.start()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    auth = flow.google.issue_code(url, "sub-1", NEW)
    good = flow.client.cookies["tracker_oauth"]
    # tampered payload with the original signature
    body, sig = good.split(".")
    flow.client.cookies.set("tracker_oauth", f"{body[:-2]}AA.{sig}")
    assert_rejected(env, flow.callback(auth, state), "sign_in_failed", before)
    # expired
    flow.client.cookies.set("tracker_oauth", good)
    env.clock.now = T0 + timedelta(minutes=11)
    assert_rejected(env, flow.callback(auth, state), "sign_in_failed", before)
    # missing
    env.clock.now = T0
    flow.client.cookies.clear()
    assert_rejected(env, flow.callback(auth, state), "sign_in_failed", before)


def test_ac_replayed_code_fails_because_cookie_is_cleared_and_google_codes_are_single_use(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env, allowlist_emails=NEW)
    url = flow.start()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    auth = flow.google.issue_code(url, "sub-1", NEW)
    cookie = flow.client.cookies["tracker_oauth"]
    assert flow.callback(auth, state).headers["location"] == f"{FRONTEND}/app"
    after_first = counts(env.db)
    # The browser's cookie was cleared, so an immediate replay has no flow.
    assert error_of(flow.callback(auth, state)) == "sign_in_failed"
    # An attacker who captured the cookie still cannot reuse the one-time code.
    flow.client.cookies.set("tracker_oauth", cookie)
    assert error_of(flow.callback(auth, state)) == "sign_in_failed"
    assert counts(env.db) == after_first


def test_ac_google_error_parameter_redirects_with_stable_codes(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.start()
    denied = flow.client.get(
        "/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert error_of(denied) == "sign_in_cancelled"
    other = flow.client.get(
        "/auth/google/callback", params={"error": "server_error"}, follow_redirects=False
    )
    assert error_of(other) == "sign_in_failed"


@pytest.mark.parametrize(
    "override",
    [
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"email_verified": False},
    ],
)
def test_ac_invalid_id_token_is_rejected_and_writes_nothing(
    env: Env,  # noqa: F811
    override: dict[str, Any],
) -> None:
    flow = Flow(env, allowlist_emails=NEW)
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW, **override), "sign_in_failed", before)


def test_ac_id_token_with_wrong_nonce_is_rejected(env: Env) -> None:  # noqa: F811
    flow = Flow(env, allowlist_emails=NEW)
    url = flow.start()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    other_nonce = url.replace("nonce=", "nonce=x")
    auth = flow.google.issue_code(other_nonce, "sub-1", NEW)
    assert error_of(flow.callback(auth, state)) == "sign_in_failed"


def test_ac_token_endpoint_failure_redirects_without_writing(env: Env) -> None:  # noqa: F811
    flow = Flow(env, allowlist_emails=NEW)
    flow.google.token_status = 500
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW), "sign_in_failed", before)


# --- US-12: the gate ---------------------------------------------------------------------------


def test_ac_gate_rejects_uninvited_person_with_no_code_and_no_allowlist(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW), "not_invited", before)


def test_ac_gate_rejects_reused_code_for_a_second_google_account(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    code = flow.invite()
    flow.submit_code(code)
    assert flow.sign_in(NEW, "sub-1").headers["location"] == f"{FRONTEND}/app"
    other = Flow(env)  # a fresh browser that learned the same code
    # The code is spent, so validation already refuses it.
    assert other.submit_code(code).status_code == 400
    # And a stale claim cookie cannot redeem it either.
    other.client.cookies.set("tracker_invite", flow.client.cookies.get("tracker_invite") or "x")
    before = counts(env.db)
    assert_rejected(env, other.sign_in("other@example.test", "sub-2"), "not_invited", before)


def test_ac_gate_rejects_code_that_expired_after_it_was_validated(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.submit_code(flow.invite(expires_at=T0 + timedelta(minutes=5)))
    env.clock.now = T0 + timedelta(minutes=6)
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW), "not_invited", before)


def test_ac_gate_rejects_code_issued_for_a_different_email(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.submit_code(flow.invite(email="intended@example.test"))
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW), "not_invited", before)
    assert (
        env.db.scalars(select(InviteCode)).one().used_at is None
    )  # still usable by the right person


def test_ac_gate_accepts_code_for_the_intended_email_ignoring_case(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.submit_code(flow.invite(email="New@Example.test"))
    assert flow.sign_in("NEW@example.test", "sub-1").headers["location"] == f"{FRONTEND}/app"
    assert env.db.scalars(select(User)).one().email == NEW


def test_ac_gate_accepts_allowlisted_email_without_a_code_and_does_not_burn_a_code(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env, allowlist_emails=f" Someone@example.test , {NEW.upper()}")
    code = flow.invite()
    flow.submit_code(code)
    assert flow.sign_in(NEW, "sub-1").headers["location"] == f"{FRONTEND}/app"
    assert env.db.scalars(select(InviteCode)).one().used_at is None


def test_ac_gate_rejects_when_the_user_cap_is_reached(env: Env) -> None:  # noqa: F811
    flow = Flow(env, max_users="1", allowlist_emails=NEW)
    env.user()  # takes the only slot
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW, "sub-9"), "not_invited", before)
    invited = Flow(env, max_users="1")
    invited.submit_code(invited.invite())  # the pending code itself needs a slot: cap exceeded
    assert_rejected(env, invited.sign_in(NEW, "sub-9"), "not_invited", counts(env.db))


def test_ac_gate_last_slot_is_usable_by_the_invite_that_holds_it(env: Env) -> None:  # noqa: F811
    flow = Flow(env, max_users="1")
    flow.submit_code(flow.invite())
    assert flow.sign_in(NEW, "sub-1").headers["location"] == f"{FRONTEND}/app"


def test_ac_tampered_invite_claim_is_ignored(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    flow.submit_code(flow.invite())
    claim = flow.client.cookies["tracker_invite"]
    flow.client.cookies.set("tracker_invite", claim[:-3] + "AAA")
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(NEW), "not_invited", before)


def test_ac_returning_user_signs_in_without_a_code_and_gets_a_new_session_each_time(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    user = User(google_sub="sub-old", email=OLD)
    env.db.add(user)
    env.db.flush()
    first = flow.sign_in(OLD, "sub-old")
    token1 = flow.client.cookies["tracker_session"]
    stale = flow.client.cookies["tracker_session"]
    second = flow.sign_in(OLD, "sub-old")
    token2 = flow.client.cookies["tracker_session"]
    assert first.headers["location"] == second.headers["location"] == f"{FRONTEND}/app"
    assert token1 == stale and token1 != token2
    rows = env.db.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
    assert len(rows) == 2 and len({r.id for r in rows}) == 2
    assert env.db.scalar(select(func.count()).select_from(User)) == 1


def test_ac_pre_login_session_cookie_is_never_promoted(env: Env) -> None:  # noqa: F811
    flow = Flow(env, allowlist_emails=NEW)
    attacker_planted = "planted-session-token"
    flow.client.cookies.set(
        "tracker_session", attacker_planted, domain="testserver.local", path="/"
    )
    flow.sign_in(NEW, "sub-1")
    assert flow.client.cookies["tracker_session"] != attacker_planted
    assert flow.client.get("/me").status_code == 200


def test_ac_disabled_user_is_rejected_and_gets_no_session(env: Env) -> None:  # noqa: F811
    flow = Flow(env)
    env.db.add(User(google_sub="sub-old", email=OLD, disabled_at=T0))
    env.db.flush()
    before = counts(env.db)
    assert_rejected(env, flow.sign_in(OLD, "sub-old"), "account_disabled", before)


# --- invite endpoint -----------------------------------------------------------------------------


def test_ac_invite_endpoint_gives_the_same_400_for_invalid_used_expired_and_malformed(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    used = flow.invite()
    flow.submit_code(used)
    flow.sign_in(NEW, "sub-1")
    expired = flow.invite(expires_at=T0 - timedelta(days=1))
    responses = [
        flow.submit_code(code) for code in (generate_code(), used, expired, "short", "!!!!")
    ]
    assert {(r.status_code, r.text) for r in responses} == {(400, '{"detail":"invalid_invite"}')}
    assert all("set-cookie" not in r.headers for r in responses)


def test_ac_invite_code_input_is_normalized_and_validation_does_not_consume_it(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    code = flow.invite()
    sloppy = f"  {code.lower().replace('-', ' ')}  "
    assert flow.submit_code(sloppy).status_code == 204
    assert flow.submit_code(code).status_code == 204
    assert env.db.scalars(select(InviteCode)).one().used_at is None


def test_ac_invite_post_from_frontend_origin_passes_and_foreign_origin_is_rejected(
    env: Env,  # noqa: F811
) -> None:
    flow = Flow(env)
    ok = flow.client.post(
        "/auth/invite", json={"code": generate_code()}, headers={"Origin": FRONTEND}
    )
    assert ok.status_code == 400  # reached the handler: no CSRF header or session is needed
    evil = flow.client.post(
        "/auth/invite", json={"code": "x"}, headers={"Origin": "https://evil.example"}
    )
    assert (evil.status_code, evil.json()) == (403, {"detail": "origin_rejected"})


# --- concurrency -------------------------------------------------------------------------------


def test_ac_same_code_used_by_two_google_accounts_at_once_lets_exactly_one_in() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    code = generate_code()
    with Session(engine) as setup:
        invite = invite_codes.create(setup, hash_code(code), T0 + timedelta(days=1))
        setup.commit()
        invite_id = invite.id
    first, second = Session(engine), Session(engine)
    outcomes: dict[str, str] = {}
    subs = {"a": f"race-{uuid.uuid4().hex}", "b": f"race-{uuid.uuid4().hex}"}

    def attempt(name: str, session: Session, commit_first: threading.Event | None) -> None:
        identity = Identity(subs[name], f"{name}@example.test", True)
        try:
            signin.admit(session, identity, invite_id, settings, T0)
            if commit_first is not None:
                commit_first.wait(timeout=5)
            session.commit()
            outcomes[name] = "in"
        except signin.SignInRejected as exc:
            session.rollback()
            outcomes[name] = exc.code

    release = threading.Event()
    a = threading.Thread(target=attempt, args=("a", first, release))
    a.start()
    b = threading.Thread(target=attempt, args=("b", second, None))
    b.start()  # blocks on the invite row until `a` commits, then loses the race
    threading.Timer(0.5, release.set).start()
    a.join(10)
    b.join(10)
    try:
        assert sorted(outcomes.values()) == ["in", "not_invited"]
        with Session(engine) as check:
            created = check.scalars(select(User).where(User.google_sub.in_(subs.values()))).all()
            assert len(created) == 1
    finally:
        first.close()
        second.close()
        with Session(engine) as cleanup:
            cleanup.execute(delete(InviteCode).where(InviteCode.id == invite_id))
            cleanup.execute(delete(User).where(User.google_sub.in_(subs.values())))
            cleanup.commit()
        engine.dispose()


def test_ac_signed_cookies_are_bound_to_their_kind(env: Env) -> None:  # noqa: F811
    from app.security import signed_cookie

    settings = get_settings()
    value = signed_cookie.sign(signed_cookie.INVITE_KIND, {"invite_id": "x"}, T0, settings)
    assert signed_cookie.verify(signed_cookie.INVITE_KIND, value, T0, 60, settings)
    assert signed_cookie.verify(signed_cookie.FLOW_KIND, value, T0, 60, settings) is None
    assert (
        signed_cookie.verify(
            signed_cookie.INVITE_KIND, value, T0 + timedelta(seconds=61), 60, settings
        )
        is None
    )
    assert signed_cookie.verify(signed_cookie.INVITE_KIND, "garbage", T0, 60, settings) is None
