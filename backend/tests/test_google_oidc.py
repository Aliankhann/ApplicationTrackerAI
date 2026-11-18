"""US-11: the OIDC client against a local fake Google (no network)."""

import logging
import urllib.parse
from typing import Any

import httpx
import pytest

from app.providers.google.oidc import (
    GoogleOidc,
    JwksCache,
    OidcError,
    new_pkce,
)
from tests.fake_google import (
    CLIENT_ID,
    CLIENT_SECRET,
    NOW,
    FakeGoogle,
    forge_hs256,
    new_key,
)

NONCE = "nonce-123"


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


def verify(google: FakeGoogle, token: str, nonce: str = NONCE) -> Any:
    oidc, _ = google.oidc()
    return oidc.verify_id_token(token, nonce)


def code_of(call: Any) -> str:
    with pytest.raises(OidcError) as info:
        call()
    return info.value.code


def test_ac_authorization_url_has_state_s256_challenge_nonce_and_only_sign_in_scopes(
    google: FakeGoogle,
) -> None:
    oidc, _ = google.oidc()
    pkce = new_pkce()
    url = oidc.build_authorization_url("st", pkce.challenge, "nn")
    parts = urllib.parse.urlsplit(url)
    query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["scope"] == "openid email profile"
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == pkce.challenge
    assert (query["state"], query["nonce"]) == ("st", "nn")
    assert query["access_type"] == "online"
    assert query["prompt"] == "select_account"
    assert query["client_id"] == CLIENT_ID
    assert "login_hint" not in query
    hinted = oidc.build_authorization_url("st", pkce.challenge, "nn", login_hint="a@example.test")
    assert "login_hint=a%40example.test" in hinted


def test_ac_pkce_verifier_is_long_random_and_challenge_is_its_s256() -> None:
    first, second = new_pkce(), new_pkce()
    assert 43 <= len(first.verifier) <= 128 and first.verifier != second.verifier
    assert "=" not in first.challenge


def test_ac_exchange_code_sends_verifier_and_secret_and_returns_id_token(
    google: FakeGoogle,
) -> None:
    oidc, _ = google.oidc()
    pkce = new_pkce()
    url = oidc.build_authorization_url("st", pkce.challenge, NONCE)
    code = google.issue_code(url, "sub-1", "a@example.test")
    assert oidc.exchange_code(code, pkce.verifier).id_token
    assert google.exchanges[0]["client_secret"] == CLIENT_SECRET


def test_ac_exchange_code_replayed_code_or_wrong_verifier_or_outage_fail_with_stable_code(
    google: FakeGoogle,
) -> None:
    oidc, _ = google.oidc()
    pkce = new_pkce()
    code = google.issue_code(oidc.build_authorization_url("s", pkce.challenge, NONCE), "s", "a@x.t")
    assert code_of(lambda: oidc.exchange_code(code, "wrong-verifier")) == "token_exchange_failed"
    oidc.exchange_code(code, pkce.verifier)
    assert code_of(lambda: oidc.exchange_code(code, pkce.verifier)) == "token_exchange_failed"
    google.token_status = 500
    assert code_of(lambda: oidc.exchange_code(code, pkce.verifier)) == "token_exchange_failed"


def test_ac_exchange_code_network_error_and_garbage_body_are_domain_errors() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    google = FakeGoogle()
    oidc, jwks = google.oidc()
    for handler in (boom, lambda r: httpx.Response(200, text="not json")):
        http = httpx.Client(transport=httpx.MockTransport(handler))
        broken = GoogleOidc(oidc._config, http, jwks)
        assert code_of(lambda b=broken: b.exchange_code("c", "v")) == "token_exchange_failed"


def test_ac_failures_never_log_code_tokens_or_secret(
    google: FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    oidc, _ = google.oidc()
    with caplog.at_level(logging.DEBUG), pytest.raises(OidcError):
        oidc.exchange_code("secret-code-value", "verifier-value")
    assert "secret-code-value" not in caplog.text and CLIENT_SECRET not in caplog.text


def test_ac_valid_token_yields_identity(google: FakeGoogle) -> None:
    token = google.sign(google.claims("sub-1", "A@Example.test", NONCE))
    identity = verify(google, token)
    assert (identity.sub, identity.email, identity.email_verified, identity.name) == (
        "sub-1",
        "A@Example.test",
        True,
        "Test Person",
    )


def test_ac_issuer_without_scheme_is_accepted(google: FakeGoogle) -> None:
    token = google.sign(google.claims("s", "a@x.t", NONCE, iss="accounts.google.com"))
    assert verify(google, token).sub == "s"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"aud": "someone-else"}, "id_token_audience"),
        ({"iss": "https://evil.example"}, "id_token_issuer"),
        ({"exp": int(NOW) - 3600}, "id_token_expired"),
        ({"iat": int(NOW) + 3600, "exp": int(NOW) + 7200}, "id_token_issued_in_future"),
        ({"email_verified": False}, "email_unverified"),
        ({"email_verified": "true"}, "email_unverified"),
    ],
)
def test_ac_bad_claims_are_rejected(
    google: FakeGoogle, override: dict[str, Any], code: str
) -> None:
    token = google.sign(google.claims("s", "a@x.t", NONCE, **override))
    assert code_of(lambda: verify(google, token)) == code


def test_ac_token_with_a_different_nonce_is_rejected(google: FakeGoogle) -> None:
    token = google.sign(google.claims("s", "a@x.t", "other-nonce"))
    assert code_of(lambda: verify(google, token)) == "id_token_nonce"


def test_ac_missing_nonce_or_required_claim_is_rejected(google: FakeGoogle) -> None:
    claims = google.claims("s", "a@x.t", NONCE)
    del claims["nonce"]
    assert code_of(lambda: verify(google, google.sign(claims))) == "id_token_nonce"
    del claims["exp"]
    assert code_of(lambda: verify(google, google.sign(claims))) == "id_token_invalid"


def test_ac_small_clock_skew_is_tolerated(google: FakeGoogle) -> None:
    token = google.sign(google.claims("s", "a@x.t", NONCE, exp=int(NOW) - 30, iat=int(NOW) - 90))
    assert verify(google, token).sub == "s"


def test_ac_alg_none_is_rejected(google: FakeGoogle) -> None:
    import jwt

    token = jwt.encode(
        google.claims("s", "a@x.t", NONCE), "", algorithm="none", headers={"kid": google.kid}
    )
    assert code_of(lambda: verify(google, token)) == "id_token_alg"


def test_ac_hs256_signed_with_the_public_key_is_rejected(google: FakeGoogle) -> None:
    token = forge_hs256(google.claims("s", "a@x.t", NONCE), google.key)
    assert code_of(lambda: verify(google, token)) == "id_token_alg"


def test_ac_signature_from_another_key_or_tampered_payload_is_rejected(google: FakeGoogle) -> None:
    forged = google.sign(google.claims("s", "a@x.t", NONCE), key=new_key())
    assert code_of(lambda: verify(google, forged)) == "id_token_invalid"
    good = google.sign(google.claims("s", "a@x.t", NONCE))
    head, body, sig = good.split(".")
    tampered = google.sign(google.claims("evil", "a@x.t", NONCE)).split(".")[1]
    assert code_of(lambda: verify(google, f"{head}.{tampered}.{sig}")) == "id_token_invalid"
    assert body != tampered
    assert code_of(lambda: verify(google, "not-a-jwt")) == "id_token_malformed"


def test_ac_unknown_kid_triggers_one_jwks_refresh_after_the_throttle(google: FakeGoogle) -> None:
    now = [NOW]
    oidc, _ = google.oidc(clock=lambda: now[0])
    oidc.verify_id_token(google.sign(google.claims("s", "a@x.t", NONCE)), NONCE)
    assert google.jwks_fetches == 1
    rotated = new_key()
    google.published["kid-2"] = rotated
    token = google.sign(google.claims("s", "a@x.t", NONCE), key=rotated, kid="kid-2")
    # Inside the throttle window an unknown kid is refused without another fetch.
    assert code_of(lambda: oidc.verify_id_token(token, NONCE)) == "id_token_unknown_kid"
    assert google.jwks_fetches == 1
    now[0] += 31
    assert oidc.verify_id_token(token, NONCE).sub == "s"
    assert google.jwks_fetches == 2
    unknown = google.sign(google.claims("s", "a@x.t", NONCE), key=rotated, kid="never")
    now[0] += 31
    assert code_of(lambda: oidc.verify_id_token(unknown, NONCE)) == "id_token_unknown_kid"
    assert google.jwks_fetches == 3  # exactly one refresh for the unknown kid


def test_ac_jwks_is_cached_until_ttl_then_refetched(google: FakeGoogle) -> None:
    now = [NOW]
    oidc, _ = google.oidc(clock=lambda: now[0])
    token = google.sign(google.claims("s", "a@x.t", NONCE))
    for _ in range(3):
        oidc.verify_id_token(token, NONCE)
    assert google.jwks_fetches == 1
    now[0] += 3601
    oidc.verify_id_token(token, NONCE)
    assert google.jwks_fetches == 2


def test_ac_jwks_outage_fails_closed(google: FakeGoogle) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    oidc, _ = google.oidc()
    broken = GoogleOidc(oidc._config, http, JwksCache(http, "https://x.example/jwks"))
    token = google.sign(google.claims("s", "a@x.t", NONCE))
    assert code_of(lambda: broken.verify_id_token(token, NONCE)) == "jwks_unavailable"


def test_ac_multi_audience_token_requires_azp_to_be_our_client(google: FakeGoogle) -> None:
    two = [CLIENT_ID, "other-client"]
    bad = google.sign(google.claims("s", "a@x.t", NONCE, aud=two, azp="other-client"))
    assert code_of(lambda: verify(google, bad)) == "id_token_azp"
    missing = google.sign(google.claims("s", "a@x.t", NONCE, aud=two))
    assert code_of(lambda: verify(google, missing)) == "id_token_azp"
    good = google.sign(google.claims("s", "a@x.t", NONCE, aud=two, azp=CLIENT_ID))
    assert verify(google, good).sub == "s"
