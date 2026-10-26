import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from config import ENVIRONMENT
from security import rate_limit

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 11 * 1024 * 1024
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"
HSTS = "max-age=31536000; includeSubDomains"


def _error(status_code: int, detail: str, headers: dict | None = None):
    return JSONResponse(
        status_code=status_code, content={"detail": detail}, headers=headers
    )


def _add_headers(request: Request, response) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if not request.url.path.startswith(DOC_PATHS):
        response.headers.setdefault("Content-Security-Policy", API_CSP)
        response.headers.setdefault("Cache-Control", "no-store")
    if ENVIRONMENT.lower() == "production":
        response.headers.setdefault("Strict-Transport-Security", HSTS)


def install_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            response = _error(status.HTTP_413_CONTENT_TOO_LARGE, "Request is too large")
            _add_headers(request, response)
            return response

        if request.method != "OPTIONS":
            try:
                rate_limit.hit(
                    "all",
                    rate_limit.client_ip(request),
                    rate_limit.GLOBAL_LIMIT_PER_MINUTE,
                    60,
                )
            except HTTPException as exc:
                response = _error(exc.status_code, exc.detail, exc.headers)
                _add_headers(request, response)
                return response

        response = await call_next(request)
        if response.status_code in (401, 403):
            logger.warning(
                "Access denied: %s %s -> %s from %s",
                request.method,
                request.url.path,
                response.status_code,
                rate_limit.client_ip(request),
            )
        _add_headers(request, response)
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "Unexpected error on %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        response = _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Something went wrong. Please try again later.",
        )
        _add_headers(request, response)
        return response
