"""MCP Relay admin MCP server (read-write tools)."""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any, AsyncIterator

def get_admin_token() -> str:
    """Read the MCP admin token at call time (not import time) so tests can vary it."""
    return (
        os.environ.get("RELAY_MCP_ADMIN_TOKEN") or os.environ.get("RELAY_ADMIN_TOKEN") or ""
    ).strip()

# The mounted StreamableHTTP app and its lifespan (session_manager.run()).
# Starlette mounts do NOT execute a child app's lifespan, so we hoist it into
# the main app's lifespan via get_mcp_lifespan(). Set by mount_mcp().
_mcp_app = None
_mcp_lifespan = None


@contextlib.asynccontextmanager
async def get_mcp_lifespan() -> AsyncIterator[None]:
    """Run the mounted MCP app's lifespan inside the main app's lifespan."""
    if _mcp_app is not None and _mcp_lifespan is not None:
        async with _mcp_lifespan(_mcp_app):
            yield
    else:
        yield


def _tools_impl() -> Any:
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("mcp-relay")

    @mcp.tool()
    def relay_list_devices() -> str:
        """List devices with online status, pending pushes, and last push summary."""
        from .main import list_devices

        return json.dumps(list_devices(), indent=2, ensure_ascii=False)

    @mcp.tool()
    async def relay_delete_device(device_id: str) -> str:
        """Delete a device and revoke its token. Client must re-run init --url to come back."""
        from .main import delete_device

        result = await delete_device(device_id)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def relay_get_device(device_id: str) -> str:
        """Get one device including agents and effective MCP documents."""
        from .main import get_device

        return json.dumps(get_device(device_id), indent=2, ensure_ascii=False)

    @mcp.tool()
    def relay_get_device_mcp(device_id: str, target: str) -> str:
        """Get mcp.json document for a device × agent target."""
        from .main import get_device

        d = get_device(device_id)
        for a in d.get("agents") or []:
            if a.get("id") == target:
                return json.dumps(a.get("mcp_document") or {"mcpServers": {}}, indent=2, ensure_ascii=False)
        return json.dumps({"error": "target not found"}, indent=2)

    @mcp.tool()
    async def relay_patch_device_agents(device_id: str, agent_config_json: str) -> str:
        """Patch device agent config (JSON string). Triggers push to device."""
        from .main import AgentConfigPatch, patch_device_agents

        cfg = json.loads(agent_config_json)
        result = await patch_device_agents(device_id, AgentConfigPatch(agent_config=cfg))
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def relay_list_push_deliveries(device_id: str = "", limit: int = 30) -> str:
        """List push delivery records."""
        from .main import list_push_deliveries

        return json.dumps(
            list_push_deliveries(device_id=device_id or None, limit=limit),
            indent=2,
            ensure_ascii=False,
        )

    @mcp.tool()
    def relay_list_logical_servers() -> str:
        from .main import list_logical

        return json.dumps(list_logical(), indent=2, ensure_ascii=False)

    @mcp.tool()
    def relay_preview_render(profile: str, target: str) -> str:
        from .main import preview_render

        return json.dumps(preview_render(profile=profile, target=target), indent=2, ensure_ascii=False)

    @mcp.tool()
    async def relay_apply_script(script: str, dry_run: bool = True, format: str = "") -> str:
        """Apply batch script to matching devices. dry_run defaults to true."""
        from .main import ScriptBody, scripts_apply

        body = ScriptBody(script=script, format=format or None, dry_run=dry_run)
        result = await scripts_apply(body)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def relay_list_audit(limit: int = 40) -> str:
        from .main import list_audit

        return json.dumps(list_audit(limit=limit), indent=2, ensure_ascii=False)

    return mcp


def mount_mcp(app) -> None:
    """Mount Streamable HTTP MCP at /mcp when RELAY_MCP_ADMIN_TOKEN is set."""
    global _mcp_app, _mcp_lifespan
    token = get_admin_token()
    if not token:
        return
    try:
        mcp = _tools_impl()
        # mcp>=2.0.0 registers routes at streamable_http_path (default "/mcp").
        # We mount this app under "/mcp" below, so register inner routes at root
        # so the outer mount prefix applies exactly once.
        inner = mcp.streamable_http_app(streamable_http_path="/")
    except Exception:
        return

    # mcp>=2.0.0: the StreamableHTTP app's lifespan must run (it initialises the
    # session manager task group). Starlette mounts skip child app lifespans, so
    # hoist it into the main app's lifespan.
    _mcp_app = inner
    _mcp_lifespan = inner.router.lifespan_context

    class _AuthMiddleware:
        def __init__(self, asgi_app, token: str):
            self.app = asgi_app
            self.token = token

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                auth = headers.get("authorization", "")
                if auth != f"Bearer {self.token}":
                    body = b'{"error":"unauthorized"}'
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 401,
                            "headers": [[b"content-type", b"application/json"], [b"content-length", str(len(body)).encode()]],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
            await self.app(scope, receive, send)

    app.mount("/mcp", _AuthMiddleware(inner, token))
