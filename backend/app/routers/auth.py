import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..auth import create_access_token, get_current_admin
from ..database import get_db
from ..models import AdminLoginAttempt, AdminUser
from ..schemas import AdminRead, AuthTokenResponse, LoginRequest, RegisterRequest
from ..security import hash_password, validate_password_strength, verify_password

router = APIRouter()


def _auth_cookie_max_age_seconds() -> int:
    return max(60, int(config.ACCESS_TOKEN_EXPIRE_MINUTES) * 60)


def _auth_cookie_secure() -> bool:
    """Only set Secure when HTTPS is in use (AUTH_COOKIE_SECURE=1). Plain HTTP droplets need false."""
    return (os.getenv("AUTH_COOKIE_SECURE", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _set_auth_cookie(response: Response, token: str) -> None:
    secure = _auth_cookie_secure()
    response.set_cookie(
        key=config.AUTH_COOKIE_NAME,
        value=token,
        max_age=_auth_cookie_max_age_seconds(),
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def _clear_auth_cookie(response: Response) -> None:
    secure = _auth_cookie_secure()
    response.delete_cookie(
        key=config.AUTH_COOKIE_NAME,
        path="/",
        secure=secure,
        samesite="lax",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _failed_attempt_count(
    db: Session,
    *,
    field,
    value: str,
    window_start: datetime,
) -> int:
    last_success = db.scalar(
        select(func.max(AdminLoginAttempt.created_at)).where(
            field == value,
            AdminLoginAttempt.success.is_(True),
        )
    )
    if last_success is not None and last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    count_since = max(window_start, last_success) if last_success else window_start
    return int(
        db.scalar(
            select(func.count(AdminLoginAttempt.id)).where(
                field == value,
                AdminLoginAttempt.success.is_(False),
                AdminLoginAttempt.created_at > count_since,
            )
        )
        or 0
    )


def _record_login_attempt(
    db: Session,
    *,
    email: str,
    ip_address: str,
    success: bool,
    created_at: datetime,
) -> None:
    db.add(
        AdminLoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success,
            created_at=created_at,
        )
    )


@router.post("/register", response_model=AdminRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    _requesting_admin: AdminUser = Depends(get_current_admin),
):
    """Create a new admin account. Requires an existing authenticated admin.

    The very first admin must be created out-of-band via ``scripts/create_admin.py``
    (documented in README) — this endpoint intentionally never allows anonymous
    self-registration, in any environment. It does not authenticate the caller as
    the new admin: no token is issued and no cookie is set for this response, so the
    calling admin's own session is left untouched.
    """
    email = payload.email.strip().lower()
    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = db.scalar(select(AdminUser).where(AdminUser.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    full_name = (payload.full_name or "").strip() or None
    admin = AdminUser(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=full_name,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return AdminRead.model_validate(admin)


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    ip_address = _client_ip(request)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=config.LOGIN_RATE_LIMIT_WINDOW_MINUTES)
    email_failures = _failed_attempt_count(
        db,
        field=AdminLoginAttempt.email,
        value=email,
        window_start=window_start,
    )
    ip_failures = _failed_attempt_count(
        db,
        field=AdminLoginAttempt.ip_address,
        value=ip_address,
        window_start=window_start,
    )
    if max(email_failures, ip_failures) >= config.LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        _record_login_attempt(
            db,
            email=email,
            ip_address=ip_address,
            success=False,
            created_at=now,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(config.LOGIN_RATE_LIMIT_WINDOW_MINUTES * 60)},
        )

    admin = db.scalar(select(AdminUser).where(AdminUser.email == email))
    if admin is None or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        _record_login_attempt(
            db,
            email=email,
            ip_address=ip_address,
            success=False,
            created_at=now,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    admin.last_login_at = now
    _record_login_attempt(
        db,
        email=email,
        ip_address=ip_address,
        success=True,
        created_at=now,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    token = create_access_token(admin)
    _set_auth_cookie(response, token)
    return AuthTokenResponse(access_token=token, admin=AdminRead.model_validate(admin))


@router.get("/me", response_model=AdminRead)
def me(admin: AdminUser = Depends(get_current_admin)):
    return AdminRead.model_validate(admin)


@router.post("/logout", response_model=dict)
def logout(
    response: Response,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    admin.token_version += 1
    db.add(admin)
    db.commit()
    _clear_auth_cookie(response)
    return {"ok": True}
