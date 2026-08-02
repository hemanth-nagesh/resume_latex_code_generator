"""FastAPI application entry point.

Lifecycle:
- Startup: configure logging, initialize Container, pre-fetch template
- Shutdown: dispose Container (close DB pool, LaTeX MCP client)

All routes are registered as sub-routers from server/api/.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import AppConfig, get_config
from server.container import Container
from server.services.logger import configure_root_logger

_logger = logging.getLogger(__name__)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Factory function: builds and returns the configured FastAPI app.

    Args:
        config: AppConfig instance. If None, loads from environment.

    Returns:
        Fully configured FastAPI application instance.
    """
    if config is None:
        config = get_config()

    configure_root_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _logger.info("Starting Resume Builder server...")
        app.state.container = Container(config)

        # Pre-fetch master template so first request is fast
        try:
            await app.state.container.template
            _logger.info("Master template pre-fetched on startup")
        except Exception:
            _logger.warning(
                "Could not pre-fetch template on startup — will retry on first request"
            )

        yield

        _logger.info("Shutting down...")
        await app.state.container.dispose()

    app = FastAPI(
        title="Resume AI Builder",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # --- Exception handler ---
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        _logger.exception("Unhandled exception on %s %s", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc) or "Internal server error",
                "type": type(exc).__name__,
            },
        )

    # --- Health check ---
    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # Register API routes
    from server.api.generate import router as generate_router
    from server.api.stream import router as stream_router
    from server.api.resume import router as resume_router
    from server.api.admin import router as admin_router
    from server.api.auth import router as auth_router

    app.include_router(auth_router)
    app.include_router(generate_router, prefix="/api")
    app.include_router(stream_router, prefix="/api")
    app.include_router(resume_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    # --- Serve React SPA (production only — when server/static/ exists) ---
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse

        app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            from fastapi.responses import FileResponse
            index = os.path.join(static_dir, "index.html")
            return FileResponse(index)

    return app


# Module-level instance for uvicorn
app = create_app()
