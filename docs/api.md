# Dreamlyn Poetry API v1

This document explains the public and administrative HTTP contracts. The authoritative machine-readable definitions are `openapi/public-v1.json` and `openapi/admin-v1.json`.

## Conventions

- Base public path: `/api/v1`.
- JSON uses UTF-8 and `application/json`.
- UUID values are canonical hyphenated strings. Invite codes are UUIDv6.
- Timestamps are UTC RFC 3339 `date-time` strings.
- Protected public endpoints use `Authorization: Bearer <access-token>`.
- Refresh tokens are accepted only through the `poetry_refresh_token` HttpOnly cookie.
- Every response includes `X-Request-ID`.

Errors use one shape:

```json
{
  "code": "validation_error",
  "message": "The request is invalid.",
  "details": [{"location": ["body", "email"], "message": "value is not a valid email address", "type": "value_error"}],
  "request_id": "8221f51e-61ab-40f4-af73-ec85e298e58b"
}
```

## Authentication

### `POST /api/v1/auth/register`

Input:

```json
{
  "email": "partner@example.com",
  "display_name": "Partner Studio",
  "password": "a-password-with-12-characters",
  "invite_code": "1f0e2ad1-5aec-6ca0-95ca-8f6a9c234661"
}
```

Output `201` (`AuthResponse`), plus a rotated HttpOnly refresh cookie:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "cd9ed582-338f-4726-9d64-ab38d7ecb687",
    "email": "partner@example.com",
    "display_name": "Partner Studio",
    "is_blocked": false,
    "created_at": "2026-07-14T10:00:00Z"
  }
}
```

The invite is consumed atomically. An invalid, revoked, or already used invite returns `409`.

### `POST /api/v1/auth/login`

Input: `{ "email": "partner@example.com", "password": "..." }`. Output: `200 AuthResponse` and refresh cookie. Invalid credentials return a generic `401`.

### `POST /api/v1/auth/refresh`

No JSON body. Requires the refresh cookie. Output: `200 TokenResponse` with `access_token`, literal `token_type: "bearer"`, and `expires_in`; the cookie is rotated.

### `POST /api/v1/auth/logout`

No body. Revokes the current refresh session, clears the cookie, and returns `204`.

### `POST /api/v1/auth/change-password`

Requires an access token. Input: `{ "current_password": "...", "new_password": "..." }`. The new password must contain 12–128 characters. Success revokes every refresh session, invalidates existing access tokens, clears the cookie, and returns `204`.

## User

### `GET /api/v1/users/me`

Returns the `UserResponse` shown inside `AuthResponse`.

## Generations

### `POST /api/v1/generations`

Input:

```json
{
  "prompt": "Slow atmospheric synthwave with distant percussion",
  "duration_seconds": 10,
  "audio_format": "mp3",
  "seed": 42
}
```

`audio_format` is `"wav" | "mp3"`; `seed` is nullable/optional. The synchronous request returns `201 GenerationResponse` after the upstream model and S3 upload complete:

```json
{
  "id": "e245ab66-28df-4aad-ac0e-e7836e0cd187",
  "prompt": "Slow atmospheric synthwave with distant percussion",
  "duration_seconds": 10,
  "audio_format": "mp3",
  "seed": 42,
  "status": "completed",
  "upstream_model": "timur",
  "error_code": null,
  "error_message": null,
  "created_at": "2026-07-14T10:00:00Z",
  "completed_at": "2026-07-14T10:00:12Z",
  "audio_url": "/api/v1/generations/e245ab66-28df-4aad-ac0e-e7836e0cd187/audio"
}
```

`status` is `"pending" | "completed" | "failed"`. Failed upstream requests return `502`, `503`, or `504` and remain in history with a safe error code/message.

### `GET /api/v1/generations`

Query: `limit` defaults to 20 and is 1–100; `offset` defaults to 0. Output:

```json
{"items": [], "total": 0, "limit": 20, "offset": 0}
```

### `GET /api/v1/generations/{generation_id}`

Returns an owned, non-deleted `GenerationResponse`; otherwise `404`.

### `DELETE /api/v1/generations/{generation_id}`

Soft-deletes owned metadata and returns `204`. It does not delete the S3 object.

### `GET /api/v1/generations/{generation_id}/audio`

Returns binary `audio/wav` or `audio/mpeg`. The optional `Range` request header is forwarded to storage. Responses may be `200` or `206` and expose `Content-Length`, `Content-Range`, and `Accept-Ranges`. TypeScript should consume this endpoint as a `Blob`, not JSON.

## Administration

All paths and `/admin/docs` use HTTP Basic credentials configured through environment variables. Base path: `/admin/api/v1`.

- `POST /invites`: input `{ "api_key": "sk-..." }`; output `201 InviteResponse`. The key is never returned.
- `GET /invites?limit=&offset=`: paginated invite metadata.
- `POST /invites/{invite_code}/revoke`: marks an invite revoked and returns it. Existing users remain active.
- `GET /users?limit=&offset=`: paginated `UserResponse` values.
- `PATCH /users/{user_id}/block`: input `{ "is_blocked": true }`; returns `UserResponse`. Blocking immediately invalidates tokens and refresh sessions.
