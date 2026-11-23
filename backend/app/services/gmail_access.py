"""Production wiring for Gmail access: decrypt a user's refresh token into a REST client."""

import uuid
from collections.abc import Callable
from functools import lru_cache

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.providers.gmail.client import GmailClient
from app.providers.gmail.errors import GmailAuthRevoked
from app.providers.gmail.pacing import TokenBucket
from app.providers.gmail.rest import RestGmailClient
from app.providers.google.oidc import HTTP_TIMEOUT, OidcConfig
from app.providers.google.tokens import CachedAccessTokens
from app.repositories import oauth_tokens as tokens_repo
from app.security.crypto import get_keyring

# Builds a Gmail client for a user; tests pass a function returning FakeGmailClient.
ClientFactory = Callable[[Session, uuid.UUID], GmailClient]


@lru_cache
def shared_http() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT)


def gmail_client_for(session: Session, user_id: uuid.UUID) -> GmailClient:
    """Raises GmailAuthRevoked when the user has no live token; the token stays in memory only."""
    refresh_token = tokens_repo.load_refresh_token(session, user_id, get_keyring())
    if refresh_token is None:
        raise GmailAuthRevoked
    config = OidcConfig.from_settings(get_settings())
    http = shared_http()
    settings = get_settings()
    return RestGmailClient(
        CachedAccessTokens(user_id, refresh_token, config, http),
        http,
        bucket=TokenBucket(settings.gmail_quota_units_per_second),
        max_concurrency=settings.gmail_max_concurrency,
    )
