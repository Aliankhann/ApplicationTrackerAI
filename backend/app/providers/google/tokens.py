"""Access tokens from a refresh token, held in memory only.

The cache is per process, keyed by user id, and never persisted or logged. `invalid_grant`
(the user revoked access) becomes `GmailAuthRevoked`.
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from app.providers.gmail.errors import GmailAuthRevoked, GmailError, GmailRateLimited
from app.providers.google.oidc import HTTP_TIMEOUT, OidcConfig

EXPIRY_SKEW = timedelta(seconds=60)
DEFAULT_LIFETIME_SECONDS = 3600


@dataclass(frozen=True)
class AccessToken:
    token: str = field(repr=False)
    expires_at: datetime
    scopes: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def refresh_access_token(
    refresh_token: str,
    config: OidcConfig,
    http: httpx.Client,
    clock: Callable[[], datetime] = _utcnow,
) -> AccessToken:
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    try:
        response = http.post(config.token_endpoint, data=form, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError:
        raise GmailError("token refresh failed") from None
    if response.status_code == 200:
        return _parse(response, clock)
    if response.status_code == 400 and _error_code(response) == "invalid_grant":
        raise GmailAuthRevoked
    if response.status_code == 429 or response.status_code >= 500:
        raise GmailRateLimited
    raise GmailError("token refresh failed")


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _parse(response: httpx.Response, clock: Callable[[], datetime]) -> AccessToken:
    try:
        body = response.json()
        token = body["access_token"]
        lifetime = int(body.get("expires_in", DEFAULT_LIFETIME_SECONDS))
        scope = body.get("scope", "")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GmailError("token refresh failed") from None
    if not isinstance(token, str) or not token:
        raise GmailError("token refresh failed")
    return AccessToken(token, clock() + timedelta(seconds=lifetime), str(scope))


class AccessTokenCache:
    """Per-process access tokens by user id; an entry is used until a minute before expiry."""

    def __init__(self) -> None:
        self._items: dict[uuid.UUID, AccessToken] = {}
        self._lock = threading.Lock()

    def get(self, user_id: uuid.UUID, now: datetime) -> AccessToken | None:
        with self._lock:
            item = self._items.get(user_id)
            if item is not None and item.expires_at - EXPIRY_SKEW <= now:
                del self._items[user_id]
                return None
            return item

    def put(self, user_id: uuid.UUID, token: AccessToken) -> None:
        with self._lock:
            self._items[user_id] = token

    def drop(self, user_id: uuid.UUID) -> None:
        with self._lock:
            self._items.pop(user_id, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


ACCESS_TOKENS = AccessTokenCache()


class CachedAccessTokens:
    """The `AccessTokenProvider` for one user: `provider(force_refresh)` returns a bearer token."""

    def __init__(
        self,
        user_id: uuid.UUID,
        refresh_token: str,
        config: OidcConfig,
        http: httpx.Client,
        cache: AccessTokenCache = ACCESS_TOKENS,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._user_id = user_id
        self._refresh_token = refresh_token
        self._config = config
        self._http = http
        self._cache = cache
        self._clock = clock

    def __call__(self, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._cache.get(self._user_id, self._clock())
            if cached is not None:
                return cached.token
        try:
            fresh = refresh_access_token(self._refresh_token, self._config, self._http, self._clock)
        except GmailAuthRevoked:
            self._cache.drop(self._user_id)
            raise
        self._cache.put(self._user_id, fresh)
        return fresh.token
