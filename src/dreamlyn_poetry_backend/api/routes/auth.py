from fastapi import APIRouter, Request, Response, status

from dreamlyn_poetry_backend.api.dependencies import CurrentUser, SessionDep, SettingsDep
from dreamlyn_poetry_backend.api.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def set_refresh_cookie(response: Response, token: str, settings: SettingsDep) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_days * 86400,
        path="/api/v1/auth",
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def clear_refresh_cookie(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/api/v1/auth",
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post("/register", response_model=AuthResponse, status_code=201, operation_id="registerUser")
async def register(
    payload: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> AuthResponse:
    user, access, refresh = await AuthService(session, settings).register(
        email=str(payload.email),
        display_name=payload.display_name,
        password=payload.password,
        invite_code=payload.invite_code,
    )
    set_refresh_cookie(response, refresh, settings)
    return AuthResponse(
        access_token=access,
        expires_in=settings.access_token_minutes * 60,
        user=user,
    )


@router.post("/login", response_model=AuthResponse, operation_id="loginUser")
async def login(
    payload: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> AuthResponse:
    user, access, refresh = await AuthService(session, settings).login(
        email=str(payload.email), password=payload.password
    )
    set_refresh_cookie(response, refresh, settings)
    return AuthResponse(access_token=access, expires_in=settings.access_token_minutes * 60, user=user)


@router.post("/refresh", response_model=TokenResponse, operation_id="refreshAccessToken")
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise AppError("refresh_token_required", "A refresh token cookie is required.", status_code=401)
    _, access, rotated_refresh = await AuthService(session, settings).refresh(refresh_token)
    set_refresh_cookie(response, rotated_refresh, settings)
    return TokenResponse(access_token=access, expires_in=settings.access_token_minutes * 60)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logoutUser")
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    await AuthService(session, settings).logout(refresh_token)
    clear_refresh_cookie(response, settings)


@router.post("/change-password", status_code=204, operation_id="changePassword")
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    await AuthService(session, settings).change_password(user, payload.current_password, payload.new_password)
    clear_refresh_cookie(response, settings)
