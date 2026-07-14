import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.core.errors import AppError

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-password-for-timing-equalization")


@dataclass(frozen=True)
class TokenClaims:
    subject: uuid.UUID
    token_type: Literal["access", "refresh"]
    jti: uuid.UUID
    token_version: int
    expires_at: datetime


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(
    *,
    user_id: uuid.UUID,
    token_type: Literal["access", "refresh"],
    token_version: int,
    expires_delta: timedelta,
    settings: Settings,
    jti: uuid.UUID | None = None,
) -> tuple[str, TokenClaims]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    claims = TokenClaims(user_id, token_type, jti or uuid.uuid4(), token_version, expires_at)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "jti": str(claims.jti),
        "ver": token_version,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, claims


def decode_token(token: str, expected_type: Literal["access", "refresh"], settings: Settings) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "jti", "ver", "exp"]},
        )
        if payload["type"] != expected_type:
            raise InvalidTokenError("Unexpected token type")
        return TokenClaims(
            subject=uuid.UUID(payload["sub"]),
            token_type=expected_type,
            jti=uuid.UUID(payload["jti"]),
            token_version=int(payload["ver"]),
            expires_at=datetime.fromtimestamp(float(payload["exp"]), UTC),
        )
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise AppError(
            "invalid_token",
            "The authentication token is invalid or expired.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
