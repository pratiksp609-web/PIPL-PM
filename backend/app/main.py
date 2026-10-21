"""FastAPI application entrypoint."""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .core import APIError
from .security import limiter

settings = get_settings()


class JsonFormatter(logging.Formatter):
    RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update({k: v for k, v in record.__dict__.items() if k not in self.RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").disabled = True


log = logging.getLogger("pipl.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if settings.is_production:
        if settings.secret_key == "change-me-in-env" or len(settings.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters in production")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE=true is required in production (serve the app over HTTPS)")
    scheduler = None
    if settings.scheduler_enabled and settings.app_env != "test":
        from .scheduler import start_scheduler

        scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        if not limiter.hit(f"api:{ip}", settings.api_rate_limit_per_minute):
            return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests"}}, status_code=429)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.url.path.startswith("/api/"):
        log.info(
            "request",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path,
                   "status": response.status_code, "ms": round((time.perf_counter() - start) * 1000, 1),
                   "user_id": getattr(request.state, "user_id", None)},
        )
    return response


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
        msg = e.get("msg", "Invalid value").removeprefix("Value error, ")
        details.append({"field": ".".join(loc), "message": msg})
    first = details[0] if details else {"field": "", "message": "Invalid input"}
    message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
    return _error(422, "validation_error", message, details)


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    log.warning("integrity error", extra={"path": request.url.path, "error": str(exc.orig)[:300]})
    text = str(exc.orig)
    if "uq_payment_txn_ref" in text or "uq_supplier_payment_ref" in text:
        return _error(409, "duplicate_reference", "A payment with this transaction reference already exists")
    if "duplicate key" in text:
        return _error(409, "duplicate", "A record with the same unique value already exists")
    if "foreign key" in text:
        return _error(409, "reference_error", "This record is linked to other records and cannot be changed this way")
    if "check constraint" in text:
        return _error(422, "constraint_violation", "One or more values are outside the allowed range")
    return _error(409, "integrity_error", "The change conflicts with existing data")


@app.exception_handler(OperationalError)
async def db_down_handler(request: Request, exc: OperationalError):
    log.error("database error", extra={"path": request.url.path, "error": str(exc)[:300]})
    return _error(503, "database_unavailable", "The database is unavailable. Please try again shortly.")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error", extra={"path": request.url.path})
    return _error(500, "internal_error", "An unexpected error occurred. The error has been logged.")


from .routers import (  # noqa: E402
    auth, calendar, clients, client_pos, dashboard, documents, notifications, payments, procurement, projects,
    quotations, reports, search, tasks, updates, users,
)

for r in (auth, users, clients, projects, dashboard, documents, quotations, client_pos, payments, procurement, tasks,
          updates, calendar, notifications, reports, search):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": settings.ai_enabled, "email_configured": settings.email_enabled}


# Serve the built frontend (production). Uploaded files are NOT served from here.
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return _error(404, "not_found", "Not found")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
