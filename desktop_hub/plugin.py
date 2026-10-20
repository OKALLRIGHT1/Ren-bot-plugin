from __future__ import annotations

from typing import Any, Dict

from plugins.composite_plugin import CompositeMixin, attach_inner_config, setting_value
from plugins.open_app.plugin import Plugin as OpenAppPlugin
from plugins.system_monitor.plugin import Plugin as SystemMonitorPlugin


OPEN_ALIASES = ("/打开", "打开", "启动")
MONITOR_ACTIONS = (
    "check",
    "all",
    "cpu",
    "memory",
    "disk",
    "temp",
    "temperature",
    "gpu",
    "start",
    "stop",
    "status",
    "set_volume",
    "mute",
    "set_brightness",
    "lock_screen",
)


class Plugin(CompositeMixin):
    allow_natural_language_direct = True
    type = "react"
    gated_action = "system.spawn_process_trusted"
    llm_commands = ["open_app", "check", "monitor"]

    def __init__(self):
        self._open = OpenAppPlugin()
        self._monitor = SystemMonitorPlugin()
        attach_inner_config(self._open, "open_app")
        attach_inner_config(self._monitor, "system_monitor")
        self._parts = {
            "open": self._open,
            "monitor": self._monitor,
        }
        self._tool_to_part = {
            "open_app": "open",
            "desktop_hub": "open",
            "check": "monitor",
            "monitor": "monitor",
        }
        self._alias_to_part = {alias: "open" for alias in OPEN_ALIASES}
        self._default_part = "monitor"
        self.reload_config()

    def reload_config(self):
        settings = getattr(self, "settings", None) or {}
        app_list = setting_value(
            settings,
            "app_list",
            [
                "计算器|calc.exe",
                "记事本|notepad.exe",
                "画图|mspaint.exe",
                "任务管理器|taskmgr.exe",
            ],
        )
        self._open.load_app_list(app_list)
        self._monitor.cpu_threshold = int(setting_value(settings, "cpu_threshold", 80) or 80)
        self._monitor.memory_threshold = int(
            setting_value(settings, "memory_threshold", 85) or 85
        )
        self._monitor.disk_threshold = int(setting_value(settings, "disk_threshold", 90) or 90)
        self._monitor.cpu_temp_threshold = int(
            setting_value(settings, "cpu_temp_threshold", 75) or 75
        )
        self._monitor.gpu_threshold = int(setting_value(settings, "gpu_threshold", 85) or 85)
        self._monitor.gpu_temp_threshold = int(
            setting_value(settings, "gpu_temp_threshold", 80) or 80
        )
        self._monitor._check_interval = int(
            setting_value(settings, "check_interval", 60) or 60
        )

    def _route_part(
        self,
        invoked_tool: str,
        invoked_alias: str,
        args: str,
        context: dict,
    ) -> str:
        part = super()._route_part(invoked_tool, invoked_alias, args, context)
        if part and (part != self._default_part or invoked_tool or invoked_alias):
            if invoked_tool or invoked_alias:
                return part
        text = str(args or "").strip()
        first = text.split(None, 1)[0].lower() if text else ""
        if any(text.startswith(alias) for alias in OPEN_ALIASES):
            return "open"
        if first in MONITOR_ACTIONS or "|||" in text:
            return "monitor"
        if self._open._match_target(text):
            return "open"
        return part or self._default_part

    async def run(self, args: str, ctx: Dict[str, Any]):
        part = self._route_part(
            str((ctx or {}).get("invoked_tool") or ""),
            str((ctx or {}).get("invoked_alias") or ""),
            args,
            ctx or {},
        )
        if part == "open":
            text = str(args or "").strip()
            for alias in OPEN_ALIASES:
                if text.startswith(alias):
                    text = text[len(alias) :].strip()
                    break
            return await self._open.run(text, ctx or {})
        return await self._monitor.run(args, ctx or {})
