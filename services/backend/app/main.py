import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import approvals, conversations, health
from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.errors import (
    ApiError,
    error_response,
    handle_api_error,
    handle_http_error,
    handle_validation_error,
)
from app.logging_config import configure_logging
from app.security.hosts import is_allowed_host

logger = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.database_url)
    app = FastAPI(title="GreenLoop", version=settings.version)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        if not is_allowed_host(request.headers.get("host", ""), settings.allowed_hosts):
            response = error_response(400, "INVALID_HOST", "Host header not allowed")
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.error("request_failed", path=request.url.path, exc_info=True)
                response = error_response(500, "INTERNAL_ERROR", "Internal server error")
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    app.include_router(health.router)
    app.include_router(conversations.router)
    app.include_router(approvals.router)
    return app
