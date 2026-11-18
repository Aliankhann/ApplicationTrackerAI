"""Standards-based Google OpenID Connect client (authorization code flow with PKCE).

Sign-in asks for `openid email profile` and `access_type=online`: no refresh token is issued, so
nothing sensitive is stored. Offline access is requested only at Gmail connect (US-31).
Authorization codes, tokens, and the client secret are never logged; failures surface as
`OidcError` with a stable code.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWK

from app.config import Settings

SIGN_IN_SCOPES = ("openid", "email", "profile")
ALLOWED_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
ALLOWED_ALGORITHMS = ("RS256",)
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
LEEWAY_SECONDS = 60
JWKS_TTL_SECONDS = 3600
JWKS_MIN_REFETCH_SECONDS = 30


class OidcError(Exception):
    """A sign-in step failed. `code` is stable and safe to log; the message is never shown."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OidcConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "OidcConfig":
        return cls(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            redirect_uri=settings.google_redirect_uri,
            issuer=settings.google_issuer,
            authorization_endpoint=settings.google_authorization_endpoint,
            token_endpoint=settings.google_token_endpoint,
            jwks_uri=settings.google_jwks_uri,
        )

    @property
    def accepted_issuers(self) -> frozenset[str]:
        return ALLOWED_ISSUERS | {self.issuer}


@dataclass(frozen=True)
class TokenResponse:
    id_token: str


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    email_verified: bool
    name: str | None = None


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


def new_pkce() -> Pkce:
    verifier = secrets.token_urlsafe(64)  # 86 chars, within the 43..128 the RFC allows
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return Pkce(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"))


def random_token() -> str:
    return secrets.token_urlsafe(32)


class JwksCache:
    """Signing keys by `kid`, cached with a TTL; an unknown `kid` triggers one throttled refetch."""

    def __init__(
        self,
        http: httpx.Client,
        jwks_uri: str,
        clock: Callable[[], float] = time.time,
        ttl: int = JWKS_TTL_SECONDS,
        min_refetch: int = JWKS_MIN_REFETCH_SECONDS,
    ) -> None:
        self._http = http
        self._uri = jwks_uri
        self._clock = clock
        self._ttl = ttl
        self._min_refetch = min_refetch
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None

    def key_for(self, kid: str) -> PyJWK:
        now = self._clock()
        stale = self._fetched_at is None or now - self._fetched_at >= self._ttl
        unknown = kid not in self._keys
        throttled = self._fetched_at is not None and now - self._fetched_at < self._min_refetch
        if stale or (unknown and not throttled):
            self._refresh(now)
        key = self._keys.get(kid)
        if key is None:
            raise OidcError("id_token_unknown_kid")
        return key

    def _refresh(self, now: float) -> None:
        try:
            response = self._http.get(self._uri, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            document = response.json()
            self._keys = {
                str(jwk["kid"]): PyJWK(jwk) for jwk in document["keys"] if jwk.get("kty") == "RSA"
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
            raise OidcError("jwks_unavailable") from exc
        self._fetched_at = now


class GoogleOidc:
    def __init__(
        self,
        config: OidcConfig,
        http: httpx.Client,
        jwks: JwksCache,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._http = http
        self._jwks = jwks
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings) -> "GoogleOidc":
        config = OidcConfig.from_settings(settings)
        http = httpx.Client(timeout=HTTP_TIMEOUT)
        return cls(config, http, JwksCache(http, config.jwks_uri))

    def build_authorization_url(
        self,
        state: str,
        code_challenge: str,
        nonce: str,
        scopes: tuple[str, ...] = SIGN_IN_SCOPES,
        login_hint: str | None = None,
    ) -> str:
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self._config.authorization_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> TokenResponse:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "redirect_uri": self._config.redirect_uri,
        }
        try:
            response = self._http.post(self._config.token_endpoint, data=form, timeout=HTTP_TIMEOUT)
            body = response.json()
            id_token = body["id_token"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OidcError("token_exchange_failed") from exc
        if response.status_code != 200 or not isinstance(id_token, str) or not id_token:
            raise OidcError("token_exchange_failed")
        return TokenResponse(id_token=id_token)

    def verify_id_token(self, id_token: str, nonce: str) -> Identity:
        key = self._signing_key(id_token)
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._config.client_id,
                options={
                    "verify_exp": False,  # exp and iat are checked below against our clock
                    "verify_iat": False,
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                },
            )
        except jwt.InvalidAudienceError as exc:
            raise OidcError("id_token_audience") from exc
        except jwt.PyJWTError as exc:
            raise OidcError("id_token_invalid") from exc
        self._check_claims(claims, nonce)
        return Identity(
            sub=str(claims["sub"]),
            email=str(claims["email"]),
            email_verified=True,
            name=claims["name"] if isinstance(claims.get("name"), str) else None,
        )

    def _signing_key(self, id_token: str) -> PyJWK:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("id_token_malformed") from exc
        kid = header.get("kid")
        if header.get("alg") not in ALLOWED_ALGORITHMS or not isinstance(kid, str):
            raise OidcError("id_token_alg")
        return self._jwks.key_for(kid)

    def _check_claims(self, claims: dict[str, object], nonce: str) -> None:
        now = self._clock()
        exp, iat = claims["exp"], claims["iat"]
        if not isinstance(exp, int | float) or not isinstance(iat, int | float):
            raise OidcError("id_token_invalid")
        if exp <= now - LEEWAY_SECONDS:
            raise OidcError("id_token_expired")
        if iat > now + LEEWAY_SECONDS:
            raise OidcError("id_token_issued_in_future")
        if claims["iss"] not in self._config.accepted_issuers:
            raise OidcError("id_token_issuer")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(
            token_nonce.encode(), nonce.encode()
        ):
            raise OidcError("id_token_nonce")
        if claims.get("email_verified") is not True:
            raise OidcError("email_unverified")
        if not isinstance(claims.get("email"), str) or not claims["email"]:
            raise OidcError("id_token_invalid")
