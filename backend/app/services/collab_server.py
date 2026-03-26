from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from ypy_websocket import ASGIServer, WebsocketServer
from ypy_websocket.yroom import YRoom
from ypy_websocket.ystore import SQLiteYStore


class LoominSQLiteYStore(SQLiteYStore):
    # Shared DB for all collaborative docs in this backend.
    db_path = "/data/yjs_ystore.db"


class LoominWebsocketServer(WebsocketServer):
    """
    WebsocketServer that creates rooms with persistent SQLite-backed stores.

    The room name is derived from the websocket path (after prefix stripping).
    """

    async def get_room(self, name: str) -> YRoom:  # type: ignore[override]
        if name not in self.rooms.keys():
            # One store instance per room/doc name; all share the same DB file.
            ystore = LoominSQLiteYStore(path=name)
            self.rooms[name] = YRoom(ready=self.rooms_ready, ystore=ystore, log=self.log)
        room = self.rooms[name]
        await self.start_room(room)
        return room


class PathStrippingASGI:
    """
    ASGI wrapper that rewrites scope['path'] so ypy-websocket room names
    are stable docIds instead of full mount paths.
    """

    def __init__(self, app: ASGIServer, prefix: str):
        self._app = app
        self._prefix = prefix.rstrip("/")

    async def __call__(
        self,
        scope: Dict[str, Any],
        receive: Callable[[], Awaitable[Dict[str, Any]]],
        send: Callable[[Dict[str, Any]], Awaitable[None]],
    ):
        if scope.get("type") == "websocket":
            path = scope.get("path") or ""
            if path.startswith(self._prefix + "/"):
                # Keep leading "/" so ypy-websocket sees distinct names like "/doc-1".
                scope = dict(scope)
                scope["path"] = path[len(self._prefix) :]
        await self._app(scope, receive, send)

