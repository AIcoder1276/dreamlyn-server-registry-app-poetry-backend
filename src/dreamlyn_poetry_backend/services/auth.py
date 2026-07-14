import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dreamlyn_poetry_backend.api.dependencies import normalize_email
from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.core.security import (
    DUMMY_PASSWORD_HASH,
    create_token,
    decode_token,
    hash_password,
    token_digest,
    verify_password,
)
from dreamlyn_poetry_backend.db.models import Invite, RefreshSession, User


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(
        self, *, email: str, display_name: str, password: str, invite_code: uuid.UUID
    ) -> tuple[User, str, str]:
        email = normalize_email(email)
        invite = await self.session.scalar(select(Invite).where(Invite.code == invite_code).with_for_update())
        if invite is None or invite.revoked_at is not None or invite.used_by_user_id is not None:
            raise AppError(
                "invite_unavailable", "The invite is invalid, revoked, or already used.", status_code=409
            )
        if await self.session.scalar(select(User.id).where(User.email == email)) is not None:
            raise AppError(
                "email_already_registered", "An account with this email already exists.", status_code=409
            )

        user = User(email=email, display_name=display_name, password_hash=hash_password(password))
        self.session.add(user)
        await self.session.flush()
        invite.used_by_user_id = user.id
        invite.used_at = datetime.now(UTC)
        try:
            access, refresh = await self._create_token_pair(user)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError(
                "registration_conflict", "The email or invite was used concurrently.", status_code=409
            ) from exc
        return user, access, refresh

    async def login(self, *, email: str, password: str) -> tuple[User, str, str]:
        user = await self.session.scalar(select(User).where(User.email == normalize_email(email)))
        encoded_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        password_valid = verify_password(password, encoded_hash)
        if user is None or not password_valid:
            raise AppError("invalid_credentials", "The email or password is incorrect.", status_code=401)
        if user.is_blocked:
            raise AppError("user_blocked", "This user account is blocked.", status_code=403)
        access, refresh = await self._create_token_pair(user)
        await self.session.commit()
        return user, access, refresh

    async def refresh(self, raw_token: str) -> tuple[User, str, str]:
        claims = decode_token(raw_token, "refresh", self.settings)
        stored = await self.session.scalar(
            select(RefreshSession).where(RefreshSession.jti == claims.jti).with_for_update()
        )
        now = datetime.now(UTC)
        expires_at = stored.expires_at if stored is not None else now
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if stored is None or stored.token_hash != token_digest(raw_token) or expires_at <= now:
            raise AppError(
                "invalid_refresh_token", "The refresh token is invalid or expired.", status_code=401
            )
        if stored.revoked_at is not None:
            await self.session.execute(
                update(RefreshSession)
                .where(RefreshSession.family_id == stored.family_id, RefreshSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await self.session.commit()
            raise AppError(
                "refresh_token_reused", "The refresh token has already been used.", status_code=401
            )

        user = await self.session.get(User, claims.subject)
        if user is None or user.token_version != claims.token_version:
            raise AppError(
                "invalid_refresh_token", "The refresh token is invalid or expired.", status_code=401
            )
        if user.is_blocked:
            raise AppError("user_blocked", "This user account is blocked.", status_code=403)

        access, refresh = await self._create_token_pair(user, family_id=stored.family_id)
        replacement = await self.session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_digest(refresh))
        )
        stored.revoked_at = now
        stored.replaced_by_id = replacement.id if replacement else None
        await self.session.commit()
        return user, access, refresh

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        try:
            claims = decode_token(raw_token, "refresh", self.settings)
        except AppError:
            return
        stored = await self.session.scalar(select(RefreshSession).where(RefreshSession.jti == claims.jti))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await self.session.commit()

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AppError("invalid_current_password", "The current password is incorrect.", status_code=400)
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        await self.session.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.commit()

    async def _create_token_pair(self, user: User, *, family_id: uuid.UUID | None = None) -> tuple[str, str]:
        access, _ = create_token(
            user_id=user.id,
            token_type="access",
            token_version=user.token_version,
            expires_delta=timedelta(minutes=self.settings.access_token_minutes),
            settings=self.settings,
        )
        refresh, claims = create_token(
            user_id=user.id,
            token_type="refresh",
            token_version=user.token_version,
            expires_delta=timedelta(days=self.settings.refresh_token_days),
            settings=self.settings,
        )
        self.session.add(
            RefreshSession(
                user_id=user.id,
                family_id=family_id or uuid.uuid4(),
                jti=claims.jti,
                token_hash=token_digest(refresh),
                expires_at=claims.expires_at,
            )
        )
        await self.session.flush()
        return access, refresh
