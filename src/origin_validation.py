"""Origin header validation for the MCP endpoints.

The Streamable HTTP transport requires servers to validate the `Origin` header
on every incoming connection to prevent DNS rebinding attacks, and to answer an
invalid one with `403 Forbidden`. Requests without an `Origin` header (non-browser
MCP clients) are allowed.

The SDK's own `TransportSecuritySettings` couples Origin validation with a strict
`Host` allow-list, which breaks deployments behind Docker or a reverse proxy, so
only the Origin check is done here.
"""

import json
import logging
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

ALLOW_ANY_ORIGIN = "*"

# Browser-based MCP clients running on the same machine (e.g. MCP Inspector)
DEFAULT_LOCAL_ORIGINS = [
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://[::1]:*",
    "https://localhost:*",
    "https://127.0.0.1:*",
    "https://[::1]:*",
]


def origin_of(url: str) -> str | None:
    """Return the `scheme://host[:port]` origin of a URL, or None if it has none."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_origin_allowed(origin: str, allowed_origins: list[str]) -> bool:
    """Match an Origin header against an allow-list.

    An entry ending in `:*` matches its origin on any port, or with no port.
    """
    origin = origin.lower()
    for allowed in allowed_origins:
        allowed = allowed.lower()
        if allowed == ALLOW_ANY_ORIGIN or origin == allowed:
            return True
        if allowed.endswith(":*"):
            base = allowed[:-2]
            if origin == base or (
                origin.startswith(base + ":") and origin[len(base) + 1 :].isdigit()
            ):
                return True
    return False


class OriginValidationMiddleware:
    """Rejects HTTP requests whose `Origin` header is not in the allow-list."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None):
        self.app = app
        # None means validation is disabled
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.allowed_origins is not None:
            origin = Headers(scope=scope).get("origin")
            if origin is not None and not is_origin_allowed(
                origin, self.allowed_origins
            ):
                logger.warning(f"Rejected MCP request with invalid Origin: {origin}")
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32600, "message": "Invalid Origin header"},
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
