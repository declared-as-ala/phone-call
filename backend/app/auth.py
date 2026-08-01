import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import AdminUser

bearer_scheme = HTTPBearer(auto_error=False)

# CSRF defense-in-depth for cookie-authenticated mutating requests (see get_current_admin).
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"
_CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_access_token(admin: AdminUser, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expires = now + (expires_delta or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES))
    header = {"alg": config.JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": admin.id,
        "email": admin.email,
        "role": admin.role,
        "tv": admin.token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    signing_input = ".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        str(config.JWT_SECRET_KEY).encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(
            str(config.JWT_SECRET_KEY).encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided = _b64url_decode(signature_part)
        if not hmac.compare_digest(expected, provided):
            raise ValueError("Invalid token signature")

        header = json.loads(_b64url_decode(header_part))
        if header.get("alg") != config.JWT_ALGORITHM:
            raise ValueError("Unsupported token algorithm")
        payload = json.loads(_b64url_decode(payload_part))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Token expired")
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_admin_from_token(db: Session, token: str) -> AdminUser:
    payload = decode_access_token(token)
    admin_id = payload.get("sub")
    admin = db.get(AdminUser, admin_id) if admin_id else None
    if admin is None or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin account is inactive or missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Logout bumps token_version, invalidating every token issued before it —
    # a coarse but simple and practical revocation mechanism for a stateless JWT.
    if int(payload.get("tv", -1)) != admin.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been signed out; please sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin


def resolve_access_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return request.cookies.get(config.AUTH_COOKIE_NAME)


def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    from_bearer = credentials is not None and credentials.scheme.lower() == "bearer"
    token = resolve_access_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not from_bearer and request.method in _CSRF_PROTECTED_METHODS:
        # Cookie-only auth on a state-changing request: require a custom header a
        # cross-site <form> POST cannot set and a cross-origin fetch/XHR would need
        # our CORS policy to allow in the first place. Requests carrying an explicit
        # Bearer token are exempt — forging that header requires already having read
        # access to the token, which a different-origin attacker never has.
        if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing or invalid CSRF header",
            )

    return get_admin_from_token(db, token)
