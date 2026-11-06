import asyncio
from types import SimpleNamespace

import pytest

from mcp_tools.plugin import Plugin
from mcp_tools import bridge


def test_schema_does_not_start_server_and_filters_allowlist():
    plugin = Plugin()
    assert plugin.get_tool_schema() is None
    plugin.settings = {"servers": [{"name": "demo", "command": "unused"}], "allowed_server_names": ["demo"]}
    plugin._bridge = SimpleNamespace(list_tools=lambda: [
        SimpleNamespace(name="mcp.demo.read", description="read"),
        SimpleNamespace(name="mcp.secret.read", description="private"),
    ])
    schema = plugin.get_tool_schema()
    assert "mcp.demo.read" in schema["description"]
    assert "mcp.secret.read" not in schema["description"]


async def test_disallowed_call_and_remote_qq_do_not_connect():
    plugin = Plugin()
    assert "allowlist" in await plugin.run("call_tool ||| mcp.demo.run ||| {}", {})
    assert plugin._bridge is None
    plugin.settings = {"allow_all_remote_tools": True}
    assert "本地" in await plugin.run("call_tool ||| mcp.demo.run ||| {}", {"source": "qq_gateway"})
    assert plugin._bridge is None


async def test_async_discovery_cancel_propagates(monkeypatch):
    started = asyncio.Event()
    closed = []
    monkeypatch.setattr(bridge, "ClientSession", object())
    client = bridge.MCPToolBridge()
    async def list_tools(cfg):
        started.set()
        try: await asyncio.Event().wait()
        finally: closed.append(cfg.name)
    monkeypatch.setattr(client, "_list_remote_tools", list_tools)
    task = asyncio.create_task(client.configure_remote_servers_async([{"name": "demo", "command": "unused"}]))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert closed == ["demo"]


async def test_stop_cancels_inflight_discovery_without_blocking_loop():
    started = asyncio.Event()
    cleaned = []
    class FakeBridge:
        async def configure_remote_servers_async(self, rows):
            started.set()
            try: await asyncio.Event().wait()
            finally: cleaned.append(True)
        def clear_remote_servers(self): pass
    plugin = Plugin()
    plugin.settings = {"servers": [{"name": "demo"}]}
    plugin._bridge = FakeBridge()
    task = asyncio.create_task(plugin.run("list_tools", {}))
    await asyncio.wait_for(started.wait(), 1)
    await plugin.stop()
    with pytest.raises(asyncio.CancelledError): await task
    assert cleaned == [True]
    assert not plugin._inflight
