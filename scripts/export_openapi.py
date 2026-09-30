"""Export the FastAPI OpenAPI schema without initializing application state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "openapi" / "openapi.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def render_schema() -> str:
    """Return a stable, review-friendly serialization of the public API schema."""

    from src.api_server import app

    schema = app.openapi()
    # Static frontend routes depend on whether a local build exists. They are not
    # part of the JSON API contract and would make the export machine-dependent.
    schema["paths"] = {
        path: item for path, item in schema.get("paths", {}).items() if path.startswith("/api/")
    }
    return (
        json.dumps(
            schema,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the deterministic AQA OpenAPI schema.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination JSON file (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the destination does not exactly match the current schema.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    rendered = render_schema()

    if args.check:
        try:
            existing = output.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"OpenAPI schema is missing: {output}", file=sys.stderr)
            return 1
        if existing != rendered:
            print(
                "OpenAPI schema is stale. Run `npm run api:generate` in frontend/.",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI schema is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Wrote OpenAPI schema: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
