import argparse
import logging
from pathlib import Path

import uvicorn

from dreamlyn_poetry_backend.openapi import export_schemas


def main() -> None:
    parser = argparse.ArgumentParser(prog="dreamlyn-poetry-backend")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the HTTP API.")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    export = subparsers.add_parser("export-openapi", help="Export committed OpenAPI contracts.")
    export.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.command == "export-openapi":
        root = Path(__file__).resolve().parents[2]
        if not export_schemas(root, check=args.check):
            parser.error("OpenAPI files are out of date; run export-openapi without --check.")
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(
        "dreamlyn_poetry_backend.app:app",
        host=getattr(args, "host", "0.0.0.0"),
        port=getattr(args, "port", 8000),
    )
