import uuid
from typing import Any

import httpx
import uuid6
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dreamlyn_poetry_backend.db.models import Invite


async def create_invite(
    session_factory: async_sessionmaker[AsyncSession], api_key: str = "sk-partner-test"
) -> uuid.UUID:
    code = uuid6.uuid6()
    async with session_factory() as session:
        session.add(Invite(code=code, api_key=api_key))
        await session.commit()
    return code


async def register_user(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "partner@example.com",
) -> tuple[dict[str, Any], uuid.UUID]:
    invite_code = await create_invite(session_factory)
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Partner Studio",
            "password": "long-enough-password",
            "invite_code": str(invite_code),
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), invite_code
