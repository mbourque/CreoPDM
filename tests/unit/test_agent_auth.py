"""Unit tests for session secret and agent Bearer tokens."""

from __future__ import annotations

from creopdm.auth_session import (
    AGENT_TOKEN_MAX_AGE_SECONDS,
    bearer_token_from_header,
    mint_agent_token,
    verify_agent_token,
)


def test_agent_token_round_trip_and_expiry():
    secret = "x" * 48
    token = mint_agent_token("user-uuid-1", secret, now=1_000_000)
    assert verify_agent_token(token, secret, now=1_000_000) == "user-uuid-1"
    assert verify_agent_token(token, secret, now=1_000_000 + 10) == "user-uuid-1"
    assert verify_agent_token(token, "wrong-secret", now=1_000_000) is None
    # expires = issued + max age; equal to expires must already be rejected.
    expires_at = 1_000_000 + AGENT_TOKEN_MAX_AGE_SECONDS
    assert verify_agent_token(token, secret, now=expires_at - 1) == "user-uuid-1"
    assert verify_agent_token(token, secret, now=expires_at) is None
    assert verify_agent_token(token, secret, now=expires_at + 1) is None
    assert verify_agent_token("not.a.token", secret) is None


def test_bearer_header_parse():
    assert bearer_token_from_header("Bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_token_from_header("bearer abc") == "abc"
    assert bearer_token_from_header("Basic abc") is None
    assert bearer_token_from_header("") is None
