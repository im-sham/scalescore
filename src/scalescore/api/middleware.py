"""
API middleware for logging and observability.

This module provides middleware for:
- Correlation ID tracking across requests
- Request/response logging
- Performance timing
"""

import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from scalescore.core.logging import bind_context, clear_context, get_logger

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track correlation IDs across requests.

    If a correlation ID is provided in the request header, it's used.
    Otherwise, a new one is generated.

    The correlation ID is:
    - Stored in a context variable for access anywhere
    - Added to the structlog context for all log entries
    - Returned in the response header
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        correlation_id = request.headers.get(
            CORRELATION_ID_HEADER,
            str(uuid.uuid4()),
        )
        request_id = str(uuid.uuid4())[:8]

        correlation_id_ctx.set(correlation_id)
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        bind_context(
            correlation_id=correlation_id,
            request_id=request_id,
        )

        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            clear_context()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all API requests with timing.

    Logs:
    - Request start with method, path, client info
    - Request completion with status code and duration
    - Request failures with error info
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        start_time = time.perf_counter()

        bind_context(
            http_method=request.method,
            http_path=request.url.path,
            http_query=str(request.query_params) if request.query_params else None,
        )

        client_ip = self._get_client_ip(request)

        logger.info(
            "request_started",
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
        )

        try:
            response = await call_next(request)

            duration_ms = (time.perf_counter() - start_time) * 1000

            log_method = logger.info if response.status_code < 400 else logger.warning

            log_method(
                "request_completed",
                http_status=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.exception(
                "request_failed",
                error_type=type(e).__name__,
                error=str(e),
                duration_ms=round(duration_ms, 2),
            )
            raise

    def _get_client_ip(self, request: Request) -> str | None:
        """Extract client IP, considering proxies."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        if request.client:
            return request.client.host

        return None


def get_correlation_id() -> str:
    """Get the current correlation ID from context."""
    return correlation_id_ctx.get()
