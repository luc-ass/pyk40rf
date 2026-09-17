"""A stand-in gateway: a real aiohttp server behind a self-signed certificate.

Mocking the transport was tried first and tied the suite to whichever aiohttp
version the mock library had caught up with. Serving the responses for real
costs a socket and exercises what the client actually does -- TLS against an
untrusted leaf, bearer headers, query strings, status codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ssl
from typing import Any

from aiohttp import web
import trustme

__all__ = ["FakeGateway", "Route"]


@dataclass(slots=True)
class Route:
    """One canned answer."""

    payload: Any = None
    status: int = 200
    body: str | None = None
    content_type: str = "application/json"


@dataclass(slots=True)
class FakeGateway:
    """Serves canned answers on one TLS port and records what was asked."""

    routes: dict[str, Route] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    auth_headers: list[str | None] = field(default_factory=list)
    queries: list[dict[str, str]] = field(default_factory=list)
    forms: list[dict[str, str]] = field(default_factory=list)
    _runner: web.AppRunner | None = field(default=None, repr=False)
    _port: int = 0

    def route(self, path: str, **kwargs: Any) -> None:
        """Register the answer for ``path``."""
        self.routes[path] = Route(**kwargs)

    @property
    def port(self) -> int:
        """The port the gateway listens on."""
        return self._port

    async def start(self) -> None:
        """Bind to a free port on localhost."""
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)

        authority = trustme.CA()
        certificate = authority.issue_cert("127.0.0.1")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        certificate.configure_cert(context)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0, ssl_context=context)
        await site.start()
        sockets = site._server.sockets
        self._port = sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Shut the server down."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.paths.append(request.path)
        self.auth_headers.append(request.headers.get("Authorization"))
        self.queries.append(dict(request.query))
        if request.method == "POST":
            # The body has to be drained here; it is gone once the handler returns.
            self.forms.append({k: str(v) for k, v in (await request.post()).items()})

        route = self.routes.get(request.path)
        if route is None:
            return web.json_response({"error": "not_found"}, status=404)
        if route.body is not None:
            return web.Response(
                text=route.body, status=route.status, content_type=route.content_type
            )
        return web.json_response(route.payload, status=route.status)
