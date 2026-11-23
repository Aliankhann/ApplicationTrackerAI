"""US-31 connect Gmail with incremental consent, against the local fake Google."""

import base64
import os
import urllib.parse
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_oidc
from app.models import AuditLog, InviteCode, OAuthToken, SyncState, TokenStatus, User
from app.providers.google.scopes import GMAIL_COMPOSE, GMAIL_READONLY, parse_scopes
from app.repositories import invite_codes, oauth_tokens
from app.repositories.invite_codes import HoldResult
from app.security.crypto import get_keyring
from app.security.invite_codes import generate_code, hash_code
from app.services import account
from tests.fake_google import CONNECT_REDIRECT_URI, FakeGoogle
from tests.test_applications_api import CSRF
from tests.test_sessions import T0, Env, cookies, env  # noqa: F401
from tests.test_signin import FRONTEND, GOOGLE_ENV

REFRESH = "1//synthetic-refresh-token"


@pytest.fixture(autouse=True)
def _keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"1:{key}")
    monkeypatch.setenv("TOKEN_ENCRYPTION_CURRENT_VERSION", "1")


class Connect:
    """A signed-in browser plus fake Google: drives connect -> consent -> callback."""

    def __init__(self, env: Env, user: User | None = None) -> None:  # noqa: F811
        self.env = env
        self.user = user or env.user()
        self.google = FakeGoogle()
        self.client = self.browser(self.user)

    def browser(self, user: User) -> TestClient:
        client = self.env.app(**GOOGLE_ENV)
        oidc, _ = self.google.oidc(clock=lambda: self.env.clock.now.timestamp())
        client.app.dependency_overrides[get_oidc] = lambda: oidc  # type: ignore[attr-defined]
        raw, csrf, _ = self.env.login(user)
        cookies(client, raw, csrf)
        client.headers[CSRF] = csrf
        return client

    def start(self, **body: Any) -> str:
        response = self.client.post("/gmail/connect", json=body)
        assert response.status_code == 200, response.text
        return str(response.json()["authorize_url"])

    def callback(self, code: str, url: str, client: TestClient | None = None) -> Any:
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
        params = {"code": code, "state": state}
        return (client or self.client).get("/gmail/callback", params=params, follow_redirects=False)

    def consent(self, **body: Any) -> Any:
        url = self.start(**body)
        return self.callback(
            self.google.issue_connect_code(url, self.user.google_sub, self.user.email), url
        )

    def tokens(self) -> list[OAuthToken]:
        self.env.db.expire_all()
        return list(self.env.db.scalars(select(OAuthToken)))

    def audit(self) -> list[str]:
        return sorted(a.action for a in self.env.db.scalars(select(AuditLog)))


def error_of(response: Any) -> str:
    assert response.status_code == 302
    location = urllib.parse.urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND}/app/settings"
    return str(urllib.parse.parse_qs(location.query)["gmail_error"][0])


def assert_rejected(c: Connect, response: Any, code: str) -> None:
    assert error_of(response) == code
    assert c.tokens() == [] and c.audit() == []  # never a token or audit row on failure
    assert 'tracker_connect=""' in response.headers.get(
        "set-cookie", ""
    ) or "tracker_connect=;" in (response.headers.get("set-cookie", ""))


def test_us31_connect_url_is_offline_consent_readonly_with_login_hint_and_pkce(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    parts = urllib.parse.urlsplit(url)
    query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert query["include_granted_scopes"] == "true"
    assert query["login_hint"] == c.user.email
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) >= 43
    assert query["redirect_uri"] == CONNECT_REDIRECT_URI and query["response_type"] == "code"
    assert query["state"] and query["nonce"]
    scopes = parse_scopes(query["scope"])
    assert scopes == {"openid", "email", GMAIL_READONLY}  # identity scopes only to verify sub
    assert GMAIL_COMPOSE not in scopes
    cookie = c.client.cookies.get("tracker_connect")
    assert cookie and "httponly" in " ".join(
        h.lower() for h in c.client.post("/gmail/connect", json={}).headers.get_list("set-cookie")
    )


def test_us31_connect_requests_compose_only_when_followups_true(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    for body, expected in (({}, False), ({"followups": False}, False), ({"followups": True}, True)):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(c.start(**body)).query)
        assert (GMAIL_COMPOSE in query["scope"][0].split()) is expected
        assert GMAIL_READONLY in query["scope"][0].split()


def test_us31_connect_requires_a_session_and_google_config(env: Env) -> None:  # noqa: F811
    raw, csrf, _ = env.login(env.user())
    plain = env.app()  # Google not configured
    cookies(plain, raw, csrf)
    assert plain.post("/gmail/connect", json={}, headers={CSRF: csrf}).status_code == 503
    assert env.app(**GOOGLE_ENV).post("/gmail/connect", json={}).status_code == 401


def test_us31_connect_rejects_unknown_body_fields(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    assert c.client.post("/gmail/connect", json={"scopes": "mail.google.com"}).status_code == 422


def test_us31_callback_stores_encrypted_token_with_granted_scopes_and_audits(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    response = c.consent()
    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/app?connected=1"
    (row,) = c.tokens()
    assert row.user_id == c.user.id and row.status == TokenStatus.ACTIVE
    assert REFRESH.encode() not in row.refresh_token_enc and REFRESH not in row.scopes
    assert oauth_tokens.load_refresh_token(env.db, c.user.id, get_keyring()) == REFRESH
    assert parse_scopes(row.scopes) >= {GMAIL_READONLY}
    assert GMAIL_COMPOSE not in row.scopes
    assert c.audit() == ["gmail_connected"]
    assert c.client.get("/gmail/status").json() == {"connected": True, "followups_enabled": False}


def test_us31_callback_account_mismatch_writes_no_token(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, "some-other-sub", "other@example.test")
    assert_rejected(c, c.callback(code, url), "account_mismatch")


def test_us31_callback_without_refresh_token_asks_to_retry_and_writes_nothing(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email, refresh_token=None)
    assert_rejected(c, c.callback(code, url), "no_refresh_token")


def test_us31_callback_without_readonly_scope_is_scope_denied(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email, scope="openid email")
    assert_rejected(c, c.callback(code, url), "scope_denied")


def test_us31_callback_with_unverified_id_token_is_connect_failed(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email, email_verified=False)
    assert_rejected(c, c.callback(code, url), "connect_failed")


@pytest.mark.parametrize("flaw", ["missing", "tampered", "expired", "state", "signin_cookie"])
def test_us31_callback_with_bad_or_expired_flow_cookie_writes_nothing(env: Env, flaw: str) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email)
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    cookie = c.client.cookies.get("tracker_connect") or ""
    if flaw == "missing":
        c.client.cookies.delete("tracker_connect")
    elif flaw == "tampered":
        c.client.cookies.delete("tracker_connect")
        c.client.cookies.set("tracker_connect", cookie[:-4] + "AAAA")
    elif flaw == "expired":
        env.clock.now += timedelta(minutes=11)
    elif flaw == "state":
        state = "forged-state"
    else:  # the sign-in flow cookie must not validate as a connect flow
        c.client.cookies.delete("tracker_connect")
        c.client.cookies.set("tracker_connect", "x.y")
    response = c.client.get(
        "/gmail/callback", params={"code": code, "state": state}, follow_redirects=False
    )
    assert_rejected(c, response, "flow_invalid")


def test_us31_flow_cookie_from_another_users_session_is_rejected(env: Env) -> None:  # noqa: F811
    a = Connect(env)
    b_user = env.user()
    url = a.start()  # A's browser starts the flow; the cookie ends up in the jar...
    stolen = a.client.cookies.get("tracker_connect")
    assert stolen
    b_client = a.browser(b_user)  # ...and B's session replays it with A's code
    b_client.cookies.set("tracker_connect", stolen)
    code = a.google.issue_connect_code(url, a.user.google_sub, a.user.email)
    response = a.callback(code, url, b_client)
    assert_rejected(a, response, "flow_invalid")


def test_us31_callback_without_a_session_redirects_and_writes_nothing(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email)
    anonymous = env.app(**GOOGLE_ENV)
    anonymous.app.dependency_overrides[get_oidc] = c.client.app.dependency_overrides[get_oidc]  # type: ignore[attr-defined]
    anonymous.cookies.set("tracker_connect", c.client.cookies.get("tracker_connect") or "")
    response = c.callback(code, url, anonymous)
    assert_rejected(c, response, "session_required")


@pytest.mark.parametrize(
    ("error", "code"), [("access_denied", "access_denied"), ("server_error", "google_error")]
)
def test_us31_google_error_param_writes_nothing(env: Env, error: str, code: str) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    response = c.client.get(
        "/gmail/callback", params={"error": error, "state": state}, follow_redirects=False
    )
    assert_rejected(c, response, code)


def test_us31_callback_reused_code_fails(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start()
    code = c.google.issue_connect_code(url, c.user.google_sub, c.user.email)
    assert c.callback(code, url).headers["location"].endswith("/app?connected=1")
    again = c.callback(code, url)
    assert error_of(again) == "flow_invalid"  # the flow cookie was cleared on success


def test_us31_enabling_followups_later_updates_scopes_and_audits_once(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    c.consent()
    assert c.client.get("/gmail/status").json()["followups_enabled"] is False
    response = c.consent(followups=True)
    assert response.headers["location"] == f"{FRONTEND}/app?connected=1"
    (row,) = c.tokens()
    assert {GMAIL_READONLY, GMAIL_COMPOSE} <= parse_scopes(row.scopes)
    assert c.audit() == ["followups_enabled", "gmail_connected"]
    assert c.client.get("/gmail/status").json() == {"connected": True, "followups_enabled": True}
    c.consent(followups=True)  # connecting again changes nothing worth auditing
    assert c.audit() == ["followups_enabled", "gmail_connected"]


def test_us31_followups_declined_at_google_keeps_read_access_and_reports_it(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    url = c.start(followups=True)
    code = c.google.issue_connect_code(
        url, c.user.google_sub, c.user.email, scope=f"openid email {GMAIL_READONLY}"
    )
    assert error_of(c.callback(code, url)) == "followups_denied"
    (row,) = c.tokens()
    assert GMAIL_COMPOSE not in row.scopes and c.audit() == ["gmail_connected"]


def test_us31_reconnect_after_revocation_reactivates_token_and_clears_revoked_sync(
    env: Env,  # noqa: F811
) -> None:
    c = Connect(env)
    c.consent()
    (row,) = c.tokens()
    row.status = TokenStatus.REVOKED
    env.db.add(SyncState(user_id=c.user.id, status="revoked", last_error="auth_revoked"))
    env.db.flush()
    c.consent()
    (row,) = c.tokens()
    assert row.status == TokenStatus.ACTIVE
    state = env.db.get(SyncState, c.user.id, populate_existing=True)
    assert state is not None and (state.status, state.last_error) == ("idle", None)


def test_us31_callback_when_google_is_not_configured_redirects_to_sign_in(env: Env) -> None:  # noqa: F811
    raw, csrf, _ = env.login(env.user())
    client = env.app()
    cookies(client, raw, csrf)
    response = client.get(
        "/gmail/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )
    assert response.status_code == 302 and "/sign-in" in response.headers["location"]


def test_us35_production_revoker_is_real_once_google_is_configured(env: Env) -> None:  # noqa: F811
    from app.api.deps import get_token_revoker
    from app.providers.google.revoke import GoogleTokenRevoker, UnconfiguredTokenRevoker

    env.app()
    assert isinstance(get_token_revoker(), UnconfiguredTokenRevoker)
    env.app(**GOOGLE_ENV)
    assert isinstance(get_token_revoker(), GoogleTokenRevoker)


def test_us31_connect_redirect_uri_defaults_to_the_sign_in_origin_and_can_be_overridden(
    env: Env,  # noqa: F811
) -> None:
    from app.config import get_settings

    env.app(**GOOGLE_ENV)
    assert get_settings().connect_redirect_uri == CONNECT_REDIRECT_URI
    env.app(google_connect_redirect_uri="https://api.example.test/custom")
    assert get_settings().connect_redirect_uri == "https://api.example.test/custom"


# --- two-phase invite: connecting Gmail completes the sign-up ------------------------------------

HOLD = timedelta(minutes=10)
CLAIM = timedelta(hours=24)
SHORT = timedelta(minutes=5)


def pending_user(
    env: Env,  # noqa: F811
    expires: timedelta = timedelta(days=14),
    claim: timedelta = CLAIM,
) -> tuple[User, InviteCode]:
    """A user created by the sign-up callback: claimed code, setup not complete."""
    invite = invite_codes.create(env.db, hash_code(generate_code()), T0 + expires)
    assert invite_codes.try_hold(env.db, invite.id, "tok", T0, HOLD) is HoldResult.HELD
    user = env.user(setup_completed_at=None)
    assert invite_codes.claim(env.db, invite.id, "tok", user.id, T0, claim)
    env.db.refresh(invite)
    return user, invite


def test_finalize_gmail_connect_consumes_the_code_and_completes_setup(env: Env) -> None:  # noqa: F811
    user, invite = pending_user(env)
    c = Connect(env, user)
    assert c.consent().headers["location"] == f"{FRONTEND}/app?connected=1"
    env.db.expire_all()
    assert invite.used_by_user_id == user.id and invite.used_at == T0
    assert invite.claimed_by_user_id is None and invite.claimed_until is None
    assert user.setup_completed_at == T0
    assert c.audit() == ["account_setup_completed", "gmail_connected"]
    assert len(c.tokens()) == 1
    assert c.client.get("/me").json()["setup_completed"] is True


def test_finalize_reclaims_a_lapsed_claim_when_the_code_is_still_free(env: Env) -> None:  # noqa: F811
    user, invite = pending_user(env, claim=SHORT)
    env.clock.now = T0 + 2 * SHORT  # the claim lapsed, and nobody cleaned up yet
    c = Connect(env, user)
    assert c.consent().headers["location"] == f"{FRONTEND}/app?connected=1"
    env.db.expire_all()
    assert invite.used_by_user_id == user.id and user.setup_completed_at is not None


def test_finalize_refuses_a_revoked_code_and_stores_no_token(env: Env) -> None:  # noqa: F811
    user, invite = pending_user(env)
    invite_codes.revoke(env.db, invite.id, T0)
    c = Connect(env, user)
    assert_rejected(c, c.consent(), "invite_expired")
    env.db.refresh(invite)
    env.db.refresh(user)
    assert invite.used_at is None and user.setup_completed_at is None


def test_finalize_refuses_a_lapsed_claim_when_the_code_itself_expired(env: Env) -> None:  # noqa: F811
    user, _ = pending_user(env, expires=timedelta(minutes=3), claim=SHORT)
    env.clock.now = T0 + 2 * SHORT
    c = Connect(env, user)
    assert_rejected(c, c.consent(), "invite_expired")


def test_finalize_refuses_a_lapsed_claim_when_the_cap_has_no_room(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = pending_user(env, claim=SHORT)
    env.clock.now = T0 + 2 * SHORT
    monkeypatch.setenv("MAX_USERS", str(invite_codes.slots_in_use(env.db, env.clock.now)))
    c = Connect(env, user)
    assert_rejected(c, c.consent(), "invite_expired")


def test_finalize_after_cleanup_removed_the_pending_user_stores_nothing(env: Env) -> None:  # noqa: F811
    user, invite = pending_user(env, claim=SHORT)
    c = Connect(env, user)
    url = c.start()
    code = c.google.issue_connect_code(url, user.google_sub, user.email)
    env.clock.now = T0 + 2 * SHORT
    assert account.delete_expired_pending(env.db, env.clock.now) == 1
    env.db.commit()
    response = c.callback(code, url)  # the session died with the account
    assert error_of(response) == "session_required"
    env.db.expire_all()
    assert c.tokens() == [] and env.db.get(User, user.id) is None
    env.db.refresh(invite)
    assert invite.claimed_by_user_id is None and invite.used_at is None


def test_connecting_gmail_again_for_a_completed_user_changes_no_invite(env: Env) -> None:  # noqa: F811
    c = Connect(env)
    c.consent()
    assert c.audit() == ["gmail_connected"]  # no account_setup_completed for a finished account
