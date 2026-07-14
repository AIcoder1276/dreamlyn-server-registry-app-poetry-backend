import base64

import httpx


def basic_header(username: str = "admin", password: str = "admin-password") -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


async def test_admin_invites_are_uuid6_and_api_key_is_not_returned(
    client: httpx.AsyncClient,
) -> None:
    unauthorized = await client.get("/admin/api/v1/invites")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"].startswith("Basic")

    created = await client.post(
        "/admin/api/v1/invites", json={"api_key": "sk-sensitive"}, headers=basic_header()
    )
    assert created.status_code == 201, created.text
    assert created.json()["code"].split("-")[2].startswith("6")
    assert "api_key" not in created.json()

    listed = await client.get("/admin/api/v1/invites", headers=basic_header())
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert "sk-sensitive" not in listed.text

    docs = await client.get("/admin/docs", headers=basic_header())
    assert docs.status_code == 200
    assert "SwaggerUIBundle" in docs.text
