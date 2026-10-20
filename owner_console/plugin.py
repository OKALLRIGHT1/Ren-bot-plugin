from __future__ import annotations

from typing import Any, Dict

from plugins.agent_runtime.plugin import Plugin as AgentRuntimePlugin
from plugins.app_control.plugin import Plugin as AppControlPlugin
from plugins.composite_plugin import CompositeMixin, attach_inner_config, setting_value
from plugins.delegate_status.plugin import Plugin as DelegateStatusPlugin
from plugins.llm_monitor.plugin import Plugin as LlmMonitorPlugin
from plugins.qq_help.plugin import Plugin as QQHelpPlugin


RESTART_ALIASES = ("/重启", "/远程重启", "/restart")
HELP_ALIASES = (
    "/帮助",
    "/功能",
    "/指令",
    "你有什么功能",
    "你会什么",
    "有哪些功能",
    "有什么指令",
)
AGENT_ALIASES = (
    "agent 自检",
    "agent 工具列表",
    "agent 能力列表",
    "agent 安装计划",
    "agent 位置",
    "代码在哪",
    "项目目录在哪",
    "agent runtime",
    "agent tools",
    "agent health",
)
DELEGATE_ALIASES = (
    "副脑任务",
    "副脑状态",
    "委托任务",
    "委托状态",
    "最近副脑任务",
    "最近委托任务",
)


class Plugin(CompositeMixin):
    allow_natural_language_direct = True
    type = "react"
    llm_commands = [
        "app_control",
        "qq_help",
        "agent_runtime",
        "delegate_status",
        "llm_monitor",
    ]

    def __init__(self):
        self._restart = AppControlPlugin()
        self._help = QQHelpPlugin()
        self._agent = AgentRuntimePlugin()
        self._delegate = DelegateStatusPlugin()
        self._monitor = LlmMonitorPlugin()
        attach_inner_config(self._restart, "app_control")
        attach_inner_config(self._help, "qq_help")
        attach_inner_config(self._agent, "agent_runtime")
        attach_inner_config(self._delegate, "delegate_status")
        attach_inner_config(self._monitor, "llm_monitor")
        self._parts = {
            "restart": self._restart,
            "help": self._help,
            "agent": self._agent,
            "delegate": self._delegate,
            "monitor": self._monitor,
        }
        self._tool_to_part = {
            "app_control": "restart",
            "qq_help": "help",
            "agent_runtime": "agent",
            "delegate_status": "delegate",
            "llm_monitor": "monitor",
        }
        self._alias_to_part = {}
        self._alias_to_part.update({alias: "restart" for alias in RESTART_ALIASES})
        self._alias_to_part.update({alias: "help" for alias in HELP_ALIASES})
        self._alias_to_part.update({alias: "agent" for alias in AGENT_ALIASES})
        self._alias_to_part.update({alias: "delegate" for alias in DELEGATE_ALIASES})
        self._default_part = "help"
        self.reload_config()

    def reload_config(self):
        settings = getattr(self, "settings", None) or {}
        self._help.settings = {
            "show_disabled": {
                "type": "bool",
                "default": bool(setting_value(settings, "show_disabled", False)),
            }
        }

    def _route_part(
        self,
        invoked_tool: str,
        invoked_alias: str,
        args: str,
        context: dict,
    ) -> str:
        part = super()._route_part(invoked_tool, invoked_alias, args, context)
        if part and part != self._default_part:
            return part
        text = str(args or "").strip()
        lowered = text.lower()
        if any(text == alias or text.startswith(alias + " ") for alias in RESTART_ALIASES):
            return "restart"
        if any(text.startswith(alias) for alias in HELP_ALIASES):
            return "help"
        if any(lowered.startswith(alias) for alias in AGENT_ALIASES):
            return "agent"
        if any(alias in text for alias in DELEGATE_ALIASES):
            return "delegate"
        if any(word in text for word in ("模型监控", "模型状态", "llm监控", "成本监控", "summary", "recent")):
            return "monitor"
        return part or self._default_part

    async def run(self, args: str, ctx: Dict[str, Any]):
        part = self._route_part(
            str((ctx or {}).get("invoked_tool") or ""),
            str((ctx or {}).get("invoked_alias") or ""),
            args,
            ctx or {},
        )
        return await self._run_part(part, args, ctx or {})
