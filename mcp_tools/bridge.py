from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import os
import shlex
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from mcp import ClientSession, StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    streamablehttp_client = None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", exclude_none=True)
        except Exception:
            try:
                return value.model_dump(exclude_none=True)
            except Exception:
                return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    return value


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

    def _worker():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _normalize_server_slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(name or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "server"


MCP_STDIO_ENV_ALLOWLIST = {
    "APPDATA",
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}


def _build_stdio_env(config_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in MCP_STDIO_ENV_ALLOWLIST:
        if key in os.environ:
            env[key] = os.environ[key]
    if isinstance(config_env, dict):
        for key, value in config_env.items():
            env[str(key)] = str(value)
    return env


@dataclass(slots=True)
class MCPToolSpec:
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    provider: str = "local"


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_sec: float = 20.0
    sse_read_timeout_sec: float = 300.0

    @property
    def slug(self) -> str:
        return _normalize_server_slug(self.name)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]], index: int = 0) -> "MCPServerConfig":
        payload = data if isinstance(data, dict) else {}
        transport = str(payload.get("transport") or "stdio").strip().lower().replace("-", "_")
        if transport == "http":
            transport = "streamable_http"
        args_value = payload.get("args") or []
        if isinstance(args_value, str):
            args = shlex.split(args_value)
        elif isinstance(args_value, list):
            args = [str(x) for x in args_value if str(x).strip()]
        else:
            args = []
        env_value = payload.get("env") or {}
        env_map = {str(k): str(v) for k, v in env_value.items()} if isinstance(env_value, dict) else {}
        headers_value = payload.get("headers") or {}
        headers_map = {str(k): str(v) for k, v in headers_value.items()} if isinstance(headers_value, dict) else {}
        return cls(
            name=str(payload.get("name") or f"server_{index + 1}").strip() or f"server_{index + 1}",
            transport=transport,
            command=str(payload.get("command") or "").strip(),
            args=args,
            env=env_map,
            cwd=str(payload.get("cwd") or "").strip(),
            url=str(payload.get("url") or "").strip(),
            headers=headers_map,
            enabled=bool(payload.get("enabled", True)),
            timeout_sec=float(payload.get("timeout_sec") or 20.0),
            sse_read_timeout_sec=float(payload.get("sse_read_timeout_sec") or 300.0),
        )


@dataclass(slots=True)
class MCPServerStatus:
    name: str
    transport: str
    enabled: bool = True
    connected: bool = False
    tool_names: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "connected": self.connected,
            "tool_count": len(self.tool_names),
            "tool_names": list(self.tool_names),
            "error": self.error,
        }


class MCPToolBridge:
    """Remote MCP client used by plugins/mcp_tools.

    Discovers stdio / streamable_http servers and invokes tools as
    `mcp.<server>.<tool>`. Each list or call opens a fresh session.
    """

    def __init__(self):
        self._local_tools: Dict[str, Callable[..., Any]] = {}
        self._specs: Dict[str, MCPToolSpec] = {}
        self._remote_configs: Dict[str, MCPServerConfig] = {}
        self._remote_routes: Dict[str, Tuple[str, str]] = {}
        self._server_status: Dict[str, MCPServerStatus] = {}

    def register_local_tool(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._local_tools[name] = handler
        self._specs[name] = MCPToolSpec(
            name=name,
            description=description,
            input_schema=input_schema or {},
            provider="local",
        )

    def list_tools(self, provider: Optional[str] = None) -> List[MCPToolSpec]:
        specs = list(self._specs.values())
        if provider:
            specs = [spec for spec in specs if spec.provider == provider]
        return sorted(specs, key=lambda spec: (spec.provider != "local", spec.provider, spec.name))

    def list_server_status(self) -> List[Dict[str, Any]]:
        return [status.to_dict() for _, status in sorted(self._server_status.items())]

    def clear_local_tools(self) -> None:
        self._local_tools.clear()
        self._specs = {name: spec for name, spec in self._specs.items() if spec.provider != "local"}

    def clear_remote_servers(self) -> None:
        self._remote_configs.clear()
        self._remote_routes.clear()
        self._server_status.clear()
        self._specs = {name: spec for name, spec in self._specs.items() if spec.provider == "local"}

    def configure_remote_servers(self, server_configs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Legacy sync API. Plugin entrypoints use the cancellable async API."""
        return _run_coro_sync(self.configure_remote_servers_async(server_configs))

    async def configure_remote_servers_async(self, server_configs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        self.clear_remote_servers()
        configs = server_configs if isinstance(server_configs, list) else []
        if not configs:
            return []

        if ClientSession is None:
            for index, item in enumerate(configs):
                cfg = MCPServerConfig.from_dict(item, index=index)
                self._server_status[cfg.name] = MCPServerStatus(
                    name=cfg.name,
                    transport=cfg.transport,
                    enabled=cfg.enabled,
                    connected=False,
                    error="python mcp 包不可用",
                )
            return self.list_server_status()

        for index, item in enumerate(configs):
            cfg = MCPServerConfig.from_dict(item, index=index)
            self._remote_configs[cfg.name] = cfg

            status = MCPServerStatus(name=cfg.name, transport=cfg.transport, enabled=cfg.enabled)
            self._server_status[cfg.name] = status

            if not cfg.enabled:
                continue

            try:
                tools = await self._list_remote_tools(cfg) or []
                self._register_remote_tools(cfg, tools)
                status.connected = True
                status.tool_names = [spec.name for spec in self.list_tools(provider=cfg.name)]
            except asyncio.CancelledError as exc:
                status.connected = False
                status.error = f"MCP discovery cancelled: {exc}"
                raise
            except Exception as exc:
                status.connected = False
                status.error = str(exc)

        return self.list_server_status()

    def _register_remote_tools(self, cfg: MCPServerConfig, tools: List[Any]) -> None:
        for tool in tools or []:
            tool_name = str(getattr(tool, "name", "") or "").strip()
            if not tool_name:
                continue
            exposed_name = f"mcp.{cfg.slug}.{tool_name}"
            description = str(getattr(tool, "description", "") or getattr(tool, "title", "") or "").strip()
            input_schema = _json_safe(getattr(tool, "inputSchema", None) or {})
            self._remote_routes[exposed_name] = (cfg.name, tool_name)
            self._specs[exposed_name] = MCPToolSpec(
                name=exposed_name,
                description=description,
                input_schema=input_schema if isinstance(input_schema, dict) else {},
                provider=cfg.name,
            )

    async def _create_remote_session(self, cfg: MCPServerConfig) -> Tuple[Any, Any]:
        if ClientSession is None:
            raise RuntimeError("python mcp 包不可用")
        # Both contexts must enter and exit in this task (AnyIO cancel scopes).
        # AsyncExitStack also unwinds partial setup on cancellation/initialize failure.
        async with AsyncExitStack() as stack:
            if cfg.transport == "stdio":
                if not cfg.command:
                    raise ValueError(f"MCP server '{cfg.name}' 缺少 command")
                params = StdioServerParameters(
                    command=cfg.command, args=list(cfg.args or []),
                    env=_build_stdio_env(cfg.env), cwd=cfg.cwd or None,
                )
                streams = await stack.enter_async_context(stdio_client(params))
                read_stream, write_stream = streams
            elif cfg.transport == "streamable_http":
                if not cfg.url:
                    raise ValueError(f"MCP server '{cfg.name}' 缺少 url")
                streams = await stack.enter_async_context(streamablehttp_client(
                    cfg.url, headers=cfg.headers or None, timeout=cfg.timeout_sec,
                    sse_read_timeout=cfg.sse_read_timeout_sec, terminate_on_close=True,
                ))
                read_stream, write_stream, _ = streams
            else:
                raise ValueError(f"不支持的 MCP transport: {cfg.transport}")
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await asyncio.wait_for(session.initialize(), timeout=cfg.timeout_sec)
            return stack.pop_all(), session

    async def _close_remote_session(self, stack: Any, session: Any) -> None:
        if stack is not None:
            await stack.aclose()

    async def _list_remote_tools(self, cfg: MCPServerConfig) -> List[Any]:
        client_ctx = None
        session = None
        try:
            client_ctx, session = await self._create_remote_session(cfg)
            result = await asyncio.wait_for(session.list_tools(), timeout=cfg.timeout_sec)
            return list(getattr(result, "tools", []) or [])
        finally:
            await self._close_remote_session(client_ctx, session)

    async def _call_remote_tool(self, cfg: MCPServerConfig, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        client_ctx = None
        session = None
        try:
            client_ctx, session = await self._create_remote_session(cfg)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments or {}),
                timeout=cfg.timeout_sec,
            )
            return _json_safe(result)
        finally:
            await self._close_remote_session(client_ctx, session)

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if name in self._local_tools:
            kwargs = arguments if isinstance(arguments, dict) else {}
            result = self._local_tools[name](**kwargs)
            if hasattr(result, "__await__"):
                result = await result
            return result

        route = self._remote_routes.get(name)
        if not route:
            raise KeyError(f"Unknown MCP tool: {name}")
        server_name, tool_name = route
        cfg = self._remote_configs.get(server_name)
        if not cfg:
            raise KeyError(f"Unknown MCP server: {server_name}")
        return await self._call_remote_tool(cfg, tool_name, arguments=arguments or {})

    async def invoke_tool(self, name: str, **kwargs: Any) -> Any:
        return await self.call_tool(name, arguments=kwargs)
