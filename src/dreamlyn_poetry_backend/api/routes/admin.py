import uuid
from datetime import UTC, datetime

import uuid6
from fastapi import APIRouter, Query
from sqlalchemy import func, select, update

from dreamlyn_poetry_backend.api.dependencies import AdminAuth, SessionDep
from dreamlyn_poetry_backend.api.schemas import (
    InviteCreateRequest,
    InvitePage,
    InviteResponse,
    UserBlockRequest,
    UserPage,
    UserResponse,
)
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.db.models import Invite, RefreshSession, User

router = APIRouter(prefix="/api/v1", tags=["administration"])


def serialize_invite(invite: Invite) -> InviteResponse:
    return InviteResponse(
        code=invite.code,
        is_revoked=invite.revoked_at is not None,
        is_used=invite.used_by_user_id is not None,
        used_by_user_id=invite.used_by_user_id,
        created_at=invite.created_at,
        revoked_at=invite.revoked_at,
        used_at=invite.used_at,
    )


@router.post("/invites", response_model=InviteResponse, status_code=201, operation_id="createInvite")
async def create_invite(payload: InviteCreateRequest, _: AdminAuth, session: SessionDep) -> InviteResponse:
    invite = Invite(code=uuid6.uuid6(), api_key=payload.api_key)
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return serialize_invite(invite)


@router.get("/invites", response_model=InvitePage, operation_id="listInvites")
async def list_invites(
    _: AdminAuth,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> InvitePage:
    total = await session.scalar(select(func.count()).select_from(Invite))
    rows = await session.scalars(
        select(Invite).order_by(Invite.created_at.desc()).limit(limit).offset(offset)
    )
    return InvitePage(
        items=[serialize_invite(row) for row in rows], total=total or 0, limit=limit, offset=offset
    )


@router.post("/invites/{invite_code}/revoke", response_model=InviteResponse, operation_id="revokeInvite")
async def revoke_invite(invite_code: uuid.UUID, _: AdminAuth, session: SessionDep) -> InviteResponse:
    invite = await session.get(Invite, invite_code)
    if invite is None:
        raise AppError("invite_not_found", "The invite was not found.", status_code=404)
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(invite)
    return serialize_invite(invite)


@router.get("/users", response_model=UserPage, operation_id="listUsers")
async def list_users(
    _: AdminAuth,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> UserPage:
    total = await session.scalar(select(func.count()).select_from(User))
    rows = await session.scalars(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))
    return UserPage(
        items=[UserResponse.model_validate(row) for row in rows], total=total or 0, limit=limit, offset=offset
    )


@router.patch("/users/{user_id}/block", response_model=UserResponse, operation_id="setUserBlocked")
async def set_user_blocked(
    user_id: uuid.UUID, payload: UserBlockRequest, _: AdminAuth, session: SessionDep
) -> UserResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "The user was not found.", status_code=404)
    user.is_blocked = payload.is_blocked
    if payload.is_blocked:
        user.token_version += 1
        await session.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)
