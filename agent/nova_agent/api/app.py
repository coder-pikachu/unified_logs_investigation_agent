"""FastAPI application: mounts the routes, binds the SSE bus to the event loop,
and starts the Change Streams watcher on startup (the agent wakes on data
changes — claim #2). Set REPLAY_MODE=1 to skip the live watcher (P6 fallback).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..watcher.change_stream import get_watcher
from .architecture import router as arch_router
from .chat import router as chat_router
from .routes import router
from .sse import bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind_loop()
    watcher = get_watcher()
    if not settings.replay_mode:
        watcher.start()
    try:
        yield
    finally:
        watcher.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="NOVA RCA Agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(chat_router)
    app.include_router(arch_router)
    return app


app = create_app()
