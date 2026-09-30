"""Smoke test for the product path users actually run.

The regular backend suite can run without a frontend build. The shipped-product
verification build ``frontend/dist`` first, which activates this test.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

pytestmark = pytest.mark.skipif(
    not (DIST_DIR / "index.html").is_file(),
    reason="frontend/dist is absent; run npm run build before the product smoke",
)


def test_fastapi_serves_the_built_product_and_public_contract() -> None:
    # Import after the skip condition has been evaluated because static routes
    # are registered from the build directory at application import time.
    from src.api_server import app

    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]

    asset_match = re.search(r'(?:src|href)="(/assets/[^"]+)"', index.text)
    assert asset_match is not None
    asset = client.get(asset_match.group(1))
    assert asset.status_code == 200
    assert asset.content

    contract = client.get("/openapi.json")
    assert contract.status_code == 200
    assert "/api/health" in contract.json()["paths"]
