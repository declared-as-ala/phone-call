from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import config
from app.auth import create_access_token, decode_access_token
from app.models import AdminLoginAttempt, AdminUser
from app.security import verify_password


def test_admin_password_is_hashed(client, test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        admin = db.scalar(select(AdminUser).where(AdminUser.email == "admin@example.com"))
        assert admin is not None
        assert admin.password_hash != "StrongPassword123!"
        assert verify_password("StrongPassword123!", admin.password_hash)
    finally:
        db.close()


def test_register_rejects_anonymous_caller(client):
    """POST /api/auth/register must never allow an unauthenticated caller to create an admin."""
    r = client.post(
        "/api/auth/register",
        json={
            "email": "newadmin@example.com",
            "password": "StrongPassword123!",
            "full_name": "New Admin",
        },
        headers={"Authorization": ""},
    )

    assert r.status_code == 401


def test_authenticated_admin_can_create_new_admin(client):
    """An authenticated admin may create another admin; the caller's own session is untouched."""
    r = client.post(
        "/api/auth/register",
        json={
            "email": "newadmin@example.com",
            "password": "StrongPassword123!",
            "full_name": "New Admin",
        },
    )

    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "newadmin@example.com"
    assert body["full_name"] == "New Admin"
    assert "access_token" not in body
    assert "password_hash" not in body

    # The calling client's session must still belong to the original admin, not the new one.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"

    # The newly created admin can log in with their own credentials.
    login = client.post(
        "/api/auth/login",
        json={"email": "newadmin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )
    assert login.status_code == 200


def test_register_rejects_duplicate_email(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "AnotherPass123!"},
    )

    assert r.status_code == 409


def test_register_rejects_weak_password(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )

    assert r.status_code == 422


def test_login_succeeds_with_correct_credentials(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["admin"]["email"] == "admin@example.com"
    assert "password_hash" not in body["admin"]


def test_login_fails_with_wrong_password(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "WrongPassword123!"},
        headers={"Authorization": ""},
    )

    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_error_does_not_reveal_whether_account_exists(client):
    known = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "WrongPassword123!"},
        headers={"Authorization": ""},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "WrongPassword123!"},
        headers={"Authorization": ""},
    )

    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json() == {"detail": "Invalid email or password"}


def test_login_locks_out_after_configured_failures(client, test_engine, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 3)

    for _ in range(3):
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "WrongPassword123!"},
            headers={"Authorization": ""},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )
    assert locked.status_code == 429
    assert locked.json() == {"detail": "Too many login attempts. Please try again later."}
    assert locked.headers["retry-after"] == str(config.LOGIN_RATE_LIMIT_WINDOW_MINUTES * 60)

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    with Session() as db:
        assert db.scalar(select(func.count(AdminLoginAttempt.id))) == 4


def test_successful_login_resets_failure_count(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 3)

    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "WrongPassword123!"},
            headers={"Authorization": ""},
        ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    ).status_code == 200
    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "WrongPassword123!"},
            headers={"Authorization": ""},
        ).status_code == 401


def test_cookie_authenticated_mutation_requires_csrf_header(client):
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )
    assert login.status_code == 200

    rejected = client.post("/api/auth/logout", headers={"Authorization": ""})
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "Missing or invalid CSRF header"

    accepted = client.post(
        "/api/auth/logout",
        headers={"Authorization": "", "X-Requested-With": "XMLHttpRequest"},
    )
    assert accepted.status_code == 200


def test_logout_invalidates_previously_issued_token(client):
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )
    token = login.json()["access_token"]

    assert client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200
    old_session = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert old_session.status_code == 401


def test_auth_cookie_is_secure_http_only_and_lax_when_enabled(client, monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
        headers={"Authorization": ""},
    )

    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=3600" in cookie


def test_access_token_expiry_is_enforced(client, test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    with Session() as db:
        admin = db.scalar(select(AdminUser).where(AdminUser.email == "admin@example.com"))
        expired = create_access_token(admin, expires_delta=timedelta(seconds=-1))

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(expired)
    assert exc_info.value.status_code == 401


def test_me_works_with_token(client):
    r = client.get("/api/auth/me")

    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"
    assert "password_hash" not in r.json()


def test_protected_call_start_rejects_without_token(client):
    r = client.post(
        "/api/calls/start",
        json={"name": "No Auth", "university": "Internal U", "phone_number": "+21626565725"},
        headers={"Authorization": ""},
    )

    assert r.status_code == 401


def test_protected_call_start_works_with_token(client):
    r = client.post(
        "/api/calls/start",
        json={"name": "With Auth", "university": "Internal U", "phone_number": "+21626565725"},
    )

    assert r.status_code == 200
    assert r.json()["call_id"]


def test_admin_approve_reject_reject_without_token(client):
    started = client.post(
        "/api/calls/start",
        json={"name": "Admin Auth", "university": "Internal U", "phone_number": "+21626565725"},
    )
    call_id = started.json()["call_id"]

    approve = client.post(
        f"/api/calls/{call_id}/admin/approve-verification",
        headers={"Authorization": ""},
    )
    reject = client.post(
        f"/api/calls/{call_id}/admin/reject-verification",
        headers={"Authorization": ""},
    )

    assert approve.status_code == 401
    assert reject.status_code == 401
