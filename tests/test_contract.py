from pathlib import Path

import pytest

from dreamlyn_poetry_backend.core.config import Settings
from dreamlyn_poetry_backend.openapi import admin_schema, export_schemas, public_schema


def test_openapi_contracts_are_complete_and_current() -> None:
    public = public_schema()
    admin = admin_schema()
    operations = [
        operation
        for path in public["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "patch", "delete"}
    ]
    assert all(operation.get("operationId") for operation in operations)
    assert "ApiError" in public["components"]["schemas"]
    assert public["components"]["securitySchemes"]["RefreshCookie"]["in"] == "cookie"
    assert admin["components"]["securitySchemes"]["HTTPBasic"]["scheme"] == "basic"
    assert export_schemas(Path(__file__).resolve().parents[1], check=True)


def test_runtime_rejects_placeholder_secrets() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings().validate_runtime_secrets()
