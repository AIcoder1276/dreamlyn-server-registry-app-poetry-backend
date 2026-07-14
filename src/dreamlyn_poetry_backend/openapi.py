import json
from pathlib import Path
from typing import Any

from dreamlyn_poetry_backend.app import build_admin_app, create_app
from dreamlyn_poetry_backend.core.config import get_settings


def public_schema() -> dict[str, Any]:
    application = create_app(get_settings())
    schema = application.openapi()
    schema["components"]["securitySchemes"]["RefreshCookie"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": get_settings().refresh_cookie_name,
    }
    refresh_path = schema["paths"]["/api/v1/auth/refresh"]["post"]
    refresh_path["security"] = [{"RefreshCookie": []}]
    return schema


def admin_schema() -> dict[str, Any]:
    return build_admin_app(get_settings()).openapi()


def render_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def export_schemas(root: Path, *, check: bool = False) -> bool:
    targets = {
        root / "openapi" / "public-v1.json": render_schema(public_schema()),
        root / "openapi" / "admin-v1.json": render_schema(admin_schema()),
    }
    current = all(
        path.exists() and path.read_text(encoding="utf-8") == content for path, content in targets.items()
    )
    if check:
        return current
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True
