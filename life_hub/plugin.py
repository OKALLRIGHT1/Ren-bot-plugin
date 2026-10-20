from __future__ import annotations

import re
from typing import Any, Dict

from plugins.composite_plugin import CompositeMixin, attach_inner_config, setting_value
from plugins.life_manager.plugin import Plugin as LifeManager
from plugins.qq_reminder.plugin import Plugin as QQReminder
from plugins.task_manager.plugin import Plugin as TaskManager
from plugins.timer.plugin import Plugin as Timer


REMINDER_ALIASES = (
    "/提醒列表",
    "/提醒删除",
    "/提醒测试",
    "/提醒",
    "提醒我",
    "打卡提醒",
    "定时提醒",
    "提醒",
)
TASK_ACTIONS = (
    "add_task",
    "list_tasks",
    "complete_task",
    "delete_task",
    "today_schedule",
    "check_tasks",
    "daily_summary",
    "suggest",
    "check_overdue",
    "check_urgent",
    "add",
    "list",
    "done",
)
LIFE_ACTIONS = (
    "add_bill",
    "list_bills",
    "add_reminder",
    "add_record",
    "记账",
    "查账",
    "账单",
)


class Plugin(CompositeMixin):
    allow_natural_language_direct = True
    type = "react"
    llm_commands = [
        "life_manager",
        "timer",
        "task_manager",
        "qq_reminder",
        "database",
        "task",
    ]

    def __init__(self):
        self._life = LifeManager()
        self._reminder = QQReminder()
        self._tasks = TaskManager()
        self._timer = Timer()
        attach_inner_config(self._life, "life_manager")
        attach_inner_config(self._reminder, "qq_reminder")
        attach_inner_config(self._tasks, "task_manager")
        attach_inner_config(self._timer, "timer")
        self._parts = {
            "life": self._life,
            "reminder": self._reminder,
            "task": self._tasks,
            "timer": self._timer,
        }
        self._tool_to_part = {
            "life_manager": "life",
            "database": "life",
            "life_hub": "life",
            "qq_reminder": "reminder",
            "task_manager": "task",
            "task": "task",
            "timer": "timer",
        }
        self._alias_to_part = {alias: "reminder" for alias in REMINDER_ALIASES}
        self._default_part = "life"
        self.reload_config()

    def reload_config(self):
        settings = getattr(self, "settings", None) or {}
        self._reminder._settings = {
            "storage_path": str(
                setting_value(settings, "storage_path", "data/qq_reminders.json")
            ),
            "scan_interval_sec": int(
                setting_value(settings, "scan_interval_sec", 20) or 20
            ),
            "default_reminder_prefix": str(
                setting_value(settings, "default_reminder_prefix", "⏰ 提醒时间到：")
            ),
        }
        self._reminder._load_reminders()

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
        first = lowered.split(None, 1)[0] if lowered else ""
        if any(text.startswith(alias) for alias in REMINDER_ALIASES):
            return "reminder"
        if "提醒我" in text or first in {"/提醒", "/提醒列表", "/提醒删除", "/提醒测试"}:
            return "reminder"
        if first in TASK_ACTIONS or first in {"待办", "todo"}:
            return "task"
        if first in LIFE_ACTIONS:
            return "life"
        if re.fullmatch(r"\d+(\s*分钟?)?", text) or first in {"倒计时", "番茄钟", "番茄"}:
            return "timer"
        if any(word in text for word in ("倒计时", "番茄钟", "番茄", "专注")):
            return "timer"
        return part or self._default_part

    async def run(self, args: str, ctx: Dict[str, Any]):
        part = self._route_part(
            str((ctx or {}).get("invoked_tool") or ""),
            str((ctx or {}).get("invoked_alias") or ""),
            args,
            ctx or {},
        )
        return await self._run_part(part, args, ctx or {})
