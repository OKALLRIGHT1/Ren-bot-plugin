"""Optional MCP client plugin. Schema reads never start servers or block the UI."""
from __future__ import annotations

import asyncio
import json

from .bridge import MCPToolBridge


class Plugin:
    name = "MCP 工具桥"
    type = "react"
    description = "列出并调用已配置且在允许列表内的 MCP 工具。"
    aliases = ["mcp_tools"]

    def __init__(self):
        self.settings = {}
        self._bridge = None
        self._signature = None
        self._lock = asyncio.Lock()
        self._inflight = set()
        self._stopped = False

    def _setting(self, key, default):
        value = self.settings.get(key, default)
        return value.get("default", default) if isinstance(value, dict) else value

    def _servers(self):
        rows = self._setting("servers", [])
        if isinstance(rows, str):
            rows = json.loads(rows)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("servers 必须为 JSON 对象数组")
        return rows

    def _names(self, key):
        names = self._setting(key, [])
        if isinstance(names, str):
            names = names.replace(",", " ").split()
        return {str(name).strip() for name in names or []}

    def _is_tool_allowed(self, name):
        if name in self._names("allowed_tool_names"):
            return True, ""
        if name.startswith("mcp.") and len(name.split(".", 2)) == 3:
            server = name.split(".", 2)[1]
            if self._setting("allow_all_remote_tools", False) or server in self._names("allowed_server_names"):
                return True, ""
        return False, "工具不在 allowlist 中，请先在插件设置中允许该服务器或工具。"

    def _ensure_bridge(self):
        if self._bridge is None:
            self._bridge = MCPToolBridge()
        return self._bridge

    async def start(self, ctx=None):
        self._stopped = False

    async def stop(self):
        self._stopped = True
        tasks = [task for task in self._inflight if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._bridge is not None:
            self._bridge.clear_remote_servers()
        self._signature = None

    def get_server_status(self):
        return self._ensure_bridge().list_server_status()

    def get_tool_schema(self):
        if not self._servers():
            return None
        tools = self._ensure_bridge().list_tools()
        descriptions = [f"{tool.name}: {tool.description[:160]}" for tool in tools if self._is_tool_allowed(tool.name)[0]]
        return {"name": "mcp_tools", "description": self.description + "\n" + "\n".join(descriptions[:40]),
                "parameters": {"type": "object", "properties": {
                    "action": {"type": "string", "enum": ["list_tools", "server_status", "call_tool"]},
                    "tool_name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["action"]}}

    def format_invocation(self, data):
        action = data.get("action", "list_tools")
        if action == "call_tool":
            return f"call_tool ||| {data.get('tool_name', '')} ||| {json.dumps(data.get('arguments', {}), ensure_ascii=False)}"
        return action

    async def run(self, args, ctx):
        source = str((ctx or {}).get("source") or "").lower()
        if source in {"qq_gateway", "napcat_qq", "qq_private", "qq_group"} or ((ctx or {}).get("channel_meta") or {}).get("adapter") == "napcat_qq":
            return "MCP 工具仅允许本地使用。"
        if self._stopped:
            return "MCP 插件已停止。"
        parts = str(args or "list_tools").split("|||", 2)
        action = parts[0].strip()
        if action not in {"list_tools", "server_status", "call_tool"}:
            return "支持 list_tools、server_status、call_tool。"
        name = parts[1].strip() if len(parts) > 1 else ""
        if action == "call_tool":
            allowed, reason = self._is_tool_allowed(name)
            if not allowed:
                return reason  # Do not connect/start an unapproved server.
        task = asyncio.current_task()
        self._inflight.add(task)
        try:
            async with self._lock:
                configs = self._servers()
                signature = json.dumps(configs, sort_keys=True)
                bridge = self._ensure_bridge()
                if signature != self._signature or action == "list_tools":
                    self._signature = None
                    await bridge.configure_remote_servers_async(configs)
                    self._signature = signature
                if action == "server_status":
                    result = bridge.list_server_status()
                elif action == "list_tools":
                    result = [{"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                              for tool in bridge.list_tools() if self._is_tool_allowed(tool.name)[0]]
                else:
                    arguments = json.loads(parts[2]) if len(parts) > 2 else {}
                    if not isinstance(arguments, dict):
                        raise ValueError("arguments 必须为 JSON 对象")
                    result = await bridge.call_tool(name, arguments)
                return json.dumps(result, ensure_ascii=False)
        except (ValueError, KeyError, RuntimeError, OSError, TimeoutError) as exc:
            from modules.security_redaction import redact_sensitive_text
            return "MCP 调用失败：" + redact_sensitive_text(str(exc))
        finally:
            self._inflight.discard(task)
