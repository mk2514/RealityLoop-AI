import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.assets import router as assets_router
from app.api.routes.auth import router as auth_router
from app.api.routes.device_credentials import router as device_credentials_router
from app.api.routes.health import router as health_router
from app.api.routes.line_models import router as line_models_router
from app.api.routes.sensor_imports import router as sensor_imports_router
from app.api.routes.simulation_runs import router as simulation_runs_router
from app.api.routes.dashboards import router as dashboards_router
from app.api.routes.telemetry import (
    device_router as device_telemetry_router,
    session_router as session_telemetry_router,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.client import close_mongo_client

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_mongo_client()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Accept",
        "Content-Type",
        "X-CSRF-Token",
        "X-Request-ID",
        "X-Import-Mapping",
        "X-File-Name",
        "Authorization",
    ],
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(assets_router, prefix="/api/v1")
app.include_router(line_models_router, prefix="/api/v1")
app.include_router(sensor_imports_router, prefix="/api/v1")
app.include_router(device_credentials_router, prefix="/api/v1")
app.include_router(session_telemetry_router, prefix="/api/v1")
app.include_router(device_telemetry_router, prefix="/api/v1")
app.include_router(simulation_runs_router, prefix="/api/v1")
app.include_router(dashboards_router, prefix="/api/v1")


@app.middleware("http")
async def request_context(request: Request, call_next):
    supplied_id = request.headers.get("X-Request-ID", "")
    try:
        request_id = str(uuid.UUID(supplied_id))
    except (ValueError, AttributeError):
        request_id = str(uuid.uuid4())

    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": request_id},
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(
        request,
        status_code=exc.status_code,
        code="http_error",
        message=message,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="The request contains invalid or missing fields.",
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "Unhandled request exception",
        extra={"request_id": request_id, "exception_type": type(exc).__name__},
    )
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected server error occurred.",
    )
