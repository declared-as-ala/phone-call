"""Tests for SIP UP account settings store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import sip_up_settings_store as store


@pytest.fixture(autouse=True)
def isolated_settings_store(monkeypatch, tmp_path):
    path = tmp_path / "sip_up_account.json"
    monkeypatch.setattr(store, "_settings_path", lambda: path)
    yield path


def test_env_lookup_falls_back_to_os_environ(monkeypatch):
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "11111111")
    assert store.env_lookup("SIPUP_OUTBOUND_CALLER_ID") == "11111111"


def test_update_settings_overrides_env_lookup(isolated_settings_store):
    store.update_settings(
        label="My SIP UP",
        sip_username="10593",
        sip_password="secret",
        outbound_caller_id="28897028",
        sip_domain="sip.sipup.org",
        sip_port=5060,
    )
    assert store.env_lookup("SIPUP_OUTBOUND_CALLER_ID") == "28897028"
    assert store.env_lookup("SIPUP_SIP_USERNAME") == "10593"
    public = store.get_public_settings()
    assert public["label"] == "My SIP UP"
    assert public["source"] == "ui"
    assert public["password_present"] is True
    raw = json.loads(isolated_settings_store.read_text(encoding="utf-8"))
    assert raw["sip_password"] != "secret"
    assert "secret" not in isolated_settings_store.read_text(encoding="utf-8")
    assert raw["sip_password"].startswith("fernet:v1:")
    assert store.env_lookup("SIPUP_SIP_PASSWORD") == "secret"


def test_update_settings_keeps_password_when_blank(isolated_settings_store):
    store.update_settings(
        sip_username="10593",
        sip_password="keep-me",
        outbound_caller_id="28897028",
    )
    store.update_settings(outbound_caller_id="393888736444", sip_password="")
    assert store.env_lookup("SIPUP_OUTBOUND_CALLER_ID") == "393888736444"
    raw = json.loads(isolated_settings_store.read_text(encoding="utf-8"))
    assert raw["sip_password"] != "keep-me"
    assert "keep-me" not in isolated_settings_store.read_text(encoding="utf-8")
    assert store.env_lookup("SIPUP_SIP_PASSWORD") == "keep-me"


def test_legacy_plaintext_password_is_migrated_on_read(isolated_settings_store):
    isolated_settings_store.write_text(
        json.dumps(
            {
                "sip_username": "10593",
                "sip_password": "legacy-secret",
                "outbound_caller_id": "28897028",
            }
        ),
        encoding="utf-8",
    )

    assert store.env_lookup("SIPUP_SIP_PASSWORD") == "legacy-secret"
    persisted = isolated_settings_store.read_text(encoding="utf-8")
    assert "legacy-secret" not in persisted
    assert json.loads(persisted)["sip_password"].startswith("fernet:v1:")


def test_wrong_encryption_key_fails_closed(isolated_settings_store, monkeypatch):
    store.update_settings(
        sip_username="10593",
        sip_password="do-not-lose-me",
        outbound_caller_id="28897028",
    )
    monkeypatch.setattr(store.config, "SIP_UP_SETTINGS_SECRET", "different-key")

    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        store.env_lookup("SIPUP_SIP_PASSWORD")

    assert "do-not-lose-me" not in isolated_settings_store.read_text(encoding="utf-8")
