"""Convenience entrypoint for launching the FastAPI application."""

from __future__ import annotations

import uvicorn

from src.config.settings import Settings
from src.service.api_app import create_app

app = create_app()


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "src.api_server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
