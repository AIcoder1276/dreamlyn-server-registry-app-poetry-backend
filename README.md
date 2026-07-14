# Dreamlyn Poetry Backend

Partner-facing API for invite-only accounts and music generation through the existing Dreamlyn AI stack.

## Architecture

The backend authenticates a partner, resolves the LiteLLM API key attached to the invite used at registration, and calls the existing route:

```text
web client -> poetry backend -> LiteLLM -> music adapter -> MusicGen -> SeaweedFS S3
```

The generation endpoint returns metadata and an authenticated backend audio URL. The client downloads that URL as a `Blob` for playback or IndexedDB storage. The backend stores metadata only; audio remains in S3.

## Development

Requirements: Python 3.12, `uv`, and PostgreSQL.

```bash
cp .env.example .env
uv sync --locked
uv run alembic upgrade head
uv run dreamlyn-poetry-backend serve --host 127.0.0.1 --port 8000
```

Useful checks:

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv build
```

Runtime documentation is intentionally disabled for the public API. Administration Swagger is available at `/admin/docs` and is protected by `ADMIN_DOCS_USERNAME` and `ADMIN_DOCS_PASSWORD`.

## Configuration

All configuration is loaded from environment variables. See [`.env.example`](.env.example) for the full list.

Security-sensitive production values:

- `JWT_SECRET`: at least 32 random bytes; never reuse the example value.
- `ADMIN_DOCS_USERNAME` and `ADMIN_DOCS_PASSWORD`: credentials for all admin routes and Swagger.
- `REFRESH_COOKIE_DOMAIN`: shared parent domain when frontend and API use subdomains.
- `CORS_ALLOWED_ORIGINS`: JSON list of exact frontend origins; wildcards are not supported with cookies.
- `DATABASE_URL`: SQLAlchemy async URL using the `postgresql+asyncpg` driver.
- `S3_ACCESS_KEY` and `S3_SECRET_KEY`: a read-only SeaweedFS identity scoped to the music bucket.
- `S3_ENDPOINT_URL`: use the internal S3 endpoint (`http://swfs-s3:8333`) in production.

The LiteLLM key is supplied when an administrator creates an invite. It is stored as plaintext by design, never returned by read endpoints, and sent only as the upstream Bearer token.

## Database Migrations

Run migrations as a one-shot deployment action before starting a new backend image:

```bash
docker compose run --rm poetry-backend uv run alembic upgrade head
```

Do not run Alembic automatically in every API replica. Generate a migration after model changes and review it before applying:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

## API Contract

The human-readable contract is in [`docs/api.md`](docs/api.md). Machine-readable OpenAPI 3.1 contracts are committed in `openapi/`.

```bash
uv run dreamlyn-poetry-backend export-openapi
uv run dreamlyn-poetry-backend export-openapi --check
```

A TypeScript frontend can generate types without running this backend:

```bash
npx openapi-typescript ../backend/openapi/public-v1.json -o src/api/schema.d.ts --immutable
```

Treat generated TypeScript as derived code. Change the backend Pydantic models, regenerate OpenAPI, and then regenerate frontend types instead of editing the declarations manually.

## Infrastructure Integration Guide

No infrastructure files are modified by this repository. When deployment is prepared, update the external infrastructure repository as follows.

1. Add a PostgreSQL service such as `app-poetry-postgres` with a named persistent volume, a health check, database/user/password values from the infrastructure `.env`, and membership in the external `dreamlyn_mesh` network.
2. Add `poetry-backend`, built from this repository, to the same network. Pass its `.env`, depend on PostgreSQL health, expose port `8000` internally, and do not publish the container port directly.
3. Before starting the new backend version, run the one-shot Alembic command shown above using the backend image and production environment.
4. Route an API hostname such as `api-poetry.${DOMAIN}` through the existing nginx service to `poetry-backend:8000`. Set request and upstream read timeouts above `GENERATION_TIMEOUT_SECONDS`.
5. Keep the web client on an explicitly configured origin such as `https://poetry.${DOMAIN}` and include that exact origin in `CORS_ALLOWED_ORIGINS`.
6. Forward `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `Range`, and `X-Request-ID`. Do not strip `Set-Cookie`, `Content-Range`, or `Accept-Ranges`.
7. Use `/health/live` for container liveness and `/health/ready` for readiness. Readiness requires PostgreSQL but deliberately does not require the GPU model to be available.

The backend, LiteLLM, and SeaweedFS must be able to resolve each other through `dreamlyn_mesh`. Only nginx should expose the backend publicly.
