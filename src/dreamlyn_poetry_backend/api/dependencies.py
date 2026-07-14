import hmac
import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dreamlyn_poetry_backend.core.config import Settings, get_settings
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.core.security import decode_token
from dreamlyn_poetry_backend.db.models import User
from dreamlyn_poetry_backend.db.session import get_session

bearer = HTTPBearer(auto_error=False)
basic = HTTPBasic(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            "authentication_required",
            "A bearer access token is required.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_token(credentials.credentials, "access", settings)
    user = await session.scalar(
        select(User).where(User.id == claims.subject).options(selectinload(User.invite))
    )
    if user is None or user.token_version != claims.token_version:
        raise AppError("invalid_token", "The authentication token is invalid or expired.", status_code=401)
    if user.is_blocked:
        raise AppError("user_blocked", "This user account is blocked.", status_code=403)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)],
) -> None:
    settings: Settings = request.app.state.settings
    valid = (
        credentials is not None
        and hmac.compare_digest(credentials.username.encode(), settings.admin_docs_username.encode())
        and hmac.compare_digest(
            credentials.password.encode(), settings.admin_docs_password.get_secret_value().encode()
        )
    )
    if not valid:
        request.state.admin_auth_failed = True
        raise AppError(
            "admin_authentication_required",
            "Valid administrator credentials are required.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Dreamlyn Poetry Administration"'},
        )


AdminAuth = Annotated[None, Depends(require_admin)]


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def new_request_id() -> str:
    return str(uuid.uuid4())
