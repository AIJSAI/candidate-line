"""The Transcribe stream borrows its credentials from boto3's chain (DR-006, the silent call of 2026-11-02)."""

import asyncio

from candidate_line.telephony.speech import boto3_credentials_resolver


def test_resolver_carries_boto3_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATESTONLY0000000")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-a-real-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token-for-the-test")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    resolver = boto3_credentials_resolver()
    identity = asyncio.run(resolver.get_identity(properties={}))
    assert identity.access_key_id == "AKIATESTONLY0000000"
    assert identity.secret_access_key == "not-a-real-secret"
    assert identity.session_token == "token-for-the-test"
