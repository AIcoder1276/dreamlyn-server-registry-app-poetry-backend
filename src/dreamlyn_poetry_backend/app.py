import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from dreamlyn_poetry_backend.api.dependencies import require_admin
from dreamlyn_poetry_backend.api.routes import admin, auth, generations, users
from dreamlyn_poetry_backend.api.schemas import ApiError, HealthResponse
from dreamlyn_poetry_backend.core.config import Settings, get_settings
from dreamlyn_poetry_backend.core.errors import AppError
from dreamlyn_poetry_backend.db.session import engine

logger = logging.getLogger(__name__)

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiError, "description": "Invalid request."},
    401: {"model": ApiError, "description": "Authentication failed."},
    403: {"model": ApiError, "description": "Access is forbidden."},
    404: {"model": ApiError, "description": "Resource not found."},
    409: {"model": ApiError, "description": "Resource state conflict."},
    422: {"model": ApiError, "description": "Request validation failed."},
    502: {"model": ApiError, "description": "Upstream service failed."},
    503: {"model": ApiError, "description": "Dependency unavailable."},
    504: {"model": ApiError, "description": "Upstream request timed out."},
}


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.settings.validate_runtime_secrets()
    yield
    await engine.dispose()


def error_payload(request: Request, code: str, message: str, details: object = None) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
    }


def install_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(request, "validation_error", "The request is invalid.", details),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error request_id=%s", getattr(request.state, "request_id", None))
        return JSONResponse(
            status_code=500,
            content=error_payload(request, "internal_error", "An internal server error occurred."),
        )


def build_admin_app(settings: Settings) -> FastAPI:
    admin_app = FastAPI(
        title="Dreamlyn Poetry Administration API",
        version=settings.app_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
	    servers=[{"url": "/admin"}],
    )
    admin_app.state.settings = settings
    admin_app.include_router(admin.router, responses=COMMON_ERROR_RESPONSES)
    install_error_handlers(admin_app)

    @admin_app.get("/docs", include_in_schema=False, dependencies=[Depends(require_admin)])
    async def admin_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/admin/openapi.json", title="Dreamlyn Poetry Administration API"
        )

    @admin_app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_admin)])
    async def admin_openapi() -> JSONResponse:
        return JSONResponse(admin_app.openapi())

    return admin_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = settings

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Range", "X-Request-ID"],
        expose_headers=["Content-Length", "Content-Range", "Accept-Ranges", "X-Request-ID"],
    )
    application.include_router(auth.router, prefix="/api/v1", responses=COMMON_ERROR_RESPONSES)
    application.include_router(users.router, prefix="/api/v1", responses=COMMON_ERROR_RESPONSES)
    application.include_router(generations.router, prefix="/api/v1", responses=COMMON_ERROR_RESPONSES)
    application.mount("/admin", build_admin_app(settings))
    install_error_handlers(application)

    @application.get("/health/live", response_model=HealthResponse, tags=["health"], operation_id="liveness")
    async def liveness() -> HealthResponse:
        return HealthResponse(status="alive")

    @application.get(
        "/health/ready",
        response_model=HealthResponse,
        tags=["health"],
        operation_id="readiness",
        responses={503: {"model": ApiError}},
    )
    async def readiness() -> HealthResponse:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise AppError("database_unavailable", "PostgreSQL is unavailable.", status_code=503) from exc
        return HealthResponse(status="ready", detail="PostgreSQL is available.")

    return application


app = create_app()
