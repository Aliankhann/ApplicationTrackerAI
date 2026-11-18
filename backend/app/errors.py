"""Domain errors shared by repositories and services."""


class NotFound(Exception):
    """The record does not exist for this user."""


class InvalidOperation(ValueError):
    """The requested change is not allowed in the current state."""
