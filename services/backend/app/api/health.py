from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/v1")
logger = structlog.get_logger()


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "error"]
    time: str


def database_is_reachable(request: Request) -> bool:
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.warning("health_database_check_failed", exc_info=True)
        return False


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request, response: Response) -> HealthResponse:
    database_ok = database_is_reachable(request)
    if not database_ok:
        response.status_code = 503
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        version=request.app.state.settings.version,
        database="ok" if database_ok else "error",
        time=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
