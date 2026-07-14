from fastapi import APIRouter

from dreamlyn_poetry_backend.api.dependencies import CurrentUser
from dreamlyn_poetry_backend.api.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, operation_id="getCurrentUser")
async def get_me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
