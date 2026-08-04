"""In-memory WebSocket hub for device long connections."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    def is_online(self, device_id: str) -> bool:
        return device_id in self._connections

    def online_device_ids(self) -> set[str]:
        return set(self._connections.keys())

    async def connect(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            old = self._connections.get(device_id)
            self._connections[device_id] = ws
        if old is not None and old is not ws:
            try:
                await old.close(code=4000, reason="replaced")
            except Exception:
                pass

    async def disconnect(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if self._connections.get(device_id) is ws:
                del self._connections[device_id]

    async def force_disconnect(self, device_id: str, *, code: int = 4001, reason: str = "device deleted") -> None:
        async with self._lock:
            ws = self._connections.pop(device_id, None)
        if ws is None:
            return
        try:
            await ws.close(code=code, reason=reason)
        except Exception:
            pass

    async def send_json(self, device_id: str, msg: dict[str, Any]) -> bool:
        ws = self._connections.get(device_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(msg))
            return True
        except Exception:
            return False


hub = ConnectionHub()
