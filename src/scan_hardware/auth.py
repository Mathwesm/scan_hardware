"""Constant-time API key verification for protected deployments."""

from __future__ import annotations

from hmac import compare_digest

from pydantic import SecretStr

MIN_API_KEY_LENGTH = 32


def validate_api_key(provided: str | None, expected: SecretStr | None) -> bool:
    """Compare a supplied key with the configured secret.

    Args:
        provided: Header value from the HTTP request.
        expected: Configured deployment secret.

    Returns:
        Whether the complete keys match.
    """
    if provided is None or expected is None:
        return False
    return compare_digest(provided, expected.get_secret_value())
