"""A local stand-in for Google's OIDC endpoints: a throwaway RSA key pair, a JWKS document, and
a token endpoint served through httpx.MockTransport. Synthetic identities only."""

import base64
import hashlib
import hmac
import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.providers.google.oidc import GoogleOidc, JwksCache, OidcConfig

CLIENT_ID = "fake-client-id.apps.example.test"
CLIENT_SECRET = "fake-client-secret-value"  # noqa: S105
REDIRECT_URI = "https://api.example.test/auth/google/callback"
CONNECT_REDIRECT_URI = "https://api.example.test/gmail/callback"
ISSUER = "https://accounts.google.com"
KID = "test-key-1"
NOW = 1_767_268_800.0  # 2026-01-01T12:00:00Z, the route tests' fake clock
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_hs256(claims: dict[str, Any], key: rsa.RSAPrivateKey, kid: str = KID) -> str:
    """Algorithm-confusion attempt: HMAC with the PEM public key as the secret."""
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    body = b64(json.dumps(claims).encode())
    sig = hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


@dataclass
class FakeGoogle:
    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    kid: str = KID
    published: dict[str, rsa.RSAPrivateKey] = field(default_factory=dict)
    jwks_fetches: int = 0
    token_status: int = 200
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    used_codes: set[str] = field(default_factory=set)
    exchanges: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.published = {self.kid: self.key}

    def claims(self, sub: str, email: str, nonce: str, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": sub,
            "email": email,
            "email_verified": True,
            "name": "Test Person",
            "nonce": nonce,
            "iat": int(NOW) - 5,
            "exp": int(NOW) + 3600,
        }
        return {**base, **overrides}

    def sign(
        self, claims: dict[str, Any], key: rsa.RSAPrivateKey | None = None, kid: str | None = None
    ) -> str:
        return jwt.encode(
            claims, key or self.key, algorithm="RS256", headers={"kid": kid or self.kid}
        )

    def issue_code(self, authorization_url: str, sub: str, email: str, **overrides: Any) -> str:
        """Play the user approving consent: bind a one-time code to this authorization request."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        code = f"code-{len(self.pending) + len(self.used_codes)}-{sub}"
        self.pending[code] = {
            "challenge": query["code_challenge"][0],
            "redirect_uri": query["redirect_uri"][0],
            "id_token": self.sign(self.claims(sub, email, query["nonce"][0], **overrides)),
            "extra": {},
        }
        return code

    def issue_connect_code(
        self,
        authorization_url: str,
        sub: str,
        email: str,
        *,
        refresh_token: str | None = "1//synthetic-refresh-token",  # noqa: S107
        scope: str | None = None,
        **overrides: Any,
    ) -> str:
        """Consent at the connect step: the response carries a refresh token and granted scopes
        (by default exactly what the authorization URL asked for)."""
        code = self.issue_code(authorization_url, sub, email, **overrides)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        extra: dict[str, Any] = {"scope": scope if scope is not None else query["scope"][0]}
        if refresh_token is not None:
            extra["refresh_token"] = refresh_token
        self.pending[code]["extra"] = extra
        return code

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == JWKS_URL:
            self.jwks_fetches += 1
            keys = [jwk_for(key, kid) for kid, key in self.published.items()]
            return httpx.Response(200, json={"keys": keys})
        if url == TOKEN_URL:
            return self._token(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in urllib.parse.parse_qs(request.content.decode()).items()}
        self.exchanges.append(form)
        if self.token_status != 200:
            return httpx.Response(self.token_status, json={"error": "server_error"})
        entry = self.pending.get(form.get("code", ""))
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        valid = (
            entry is not None
            and form.get("client_id") == CLIENT_ID
            and form.get("client_secret") == CLIENT_SECRET
            and form.get("redirect_uri") == entry["redirect_uri"]
            and form.get("grant_type") == "authorization_code"
            and b64(digest) == entry["challenge"]
        )
        if not valid or entry is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        del self.pending[form["code"]]  # single use, like the real endpoint
        self.used_codes.add(form["code"])
        body = {"id_token": entry["id_token"], "access_token": "x", **entry["extra"]}
        return httpx.Response(200, json=body)

    def oidc(self, clock: Callable[[], float] = lambda: NOW) -> tuple[GoogleOidc, JwksCache]:
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        config = OidcConfig(
            CLIENT_ID,
            CLIENT_SECRET,
            REDIRECT_URI,
            ISSUER,
            "https://accounts.google.com/o/oauth2/v2/auth",
            TOKEN_URL,
            JWKS_URL,
        )
        jwks = JwksCache(http, JWKS_URL, clock=clock)
        return GoogleOidc(config, http, jwks, clock=clock), jwks
