"""Entrypoint: `python -m nova_agent` serves the FastAPI app + watcher."""
from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run(
        "nova_agent.api.app:app",
        host="0.0.0.0",
        port=settings.agent_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
