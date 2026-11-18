"""Google OAuth scopes the app asks for, and helpers over a stored space-separated scope string."""

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
# Needed so the connect step returns an ID token to prove the same Google account is connecting.
# Both were already granted at sign-in, so the consent screen shows nothing new for them.
IDENTITY_SCOPES = ("openid", "email")


def connect_scopes(followups: bool) -> tuple[str, ...]:
    gmail = (GMAIL_READONLY, GMAIL_COMPOSE) if followups else (GMAIL_READONLY,)
    return (*IDENTITY_SCOPES, *gmail)


def parse_scopes(scopes: str) -> frozenset[str]:
    return frozenset(scopes.split())


def can_read(scopes: str) -> bool:
    return GMAIL_READONLY in parse_scopes(scopes)


def can_compose(scopes: str) -> bool:
    return GMAIL_COMPOSE in parse_scopes(scopes)
