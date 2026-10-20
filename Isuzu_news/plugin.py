"""日报：图片日报 + 天气查询。"""

from pathlib import Path
import sys
from typing import Any, Dict, Optional

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from magic_daily.plugin_impl import Plugin as DailyPlugin

from plugins.composite_plugin import attach_inner_config, start_inners, stop_inners
from plugins.info_gateway.plugin import Plugin as WeatherPlugin


WEATHER_ALIASES = ("/api", "/info", "/信息源")
WEATHER_TOOLS = {"info_gateway", "weather_now", "weather_7d"}


class Plugin(DailyPlugin):
    llm_commands = ["info_gateway"]
    direct_command_aliases = ["/日报", "/魔法日报", "/api", "/info", "/信息源"]

    def __init__(self):
        super().__init__()
        self._weather = WeatherPlugin()
        attach_inner_config(self._weather, "info_gateway")
        self.reload_config()

    def reload_config(self):
        super().reload_config()
        weather = getattr(self, "_weather", None)
        if weather is None:
            return
        settings = getattr(self, "settings", None)
        if isinstance(settings, dict) and settings:
            weather.settings = settings
            return
        token = ""
        if isinstance(getattr(self, "_settings", None), dict):
            token = str(self._settings.get("api_token") or "").strip()
        if token:
            weather.settings = {"api_token": {"type": "secret", "default": token}}

    def get_tool_schema(self):
        return self._weather.get_tool_schema()

    def get_capabilities(self):
        return self._weather.get_capabilities()

    def format_invocation(self, arguments, tool_name=None):
        if str(tool_name or "") in WEATHER_TOOLS or str(
            (arguments or {}).get("capability") or ""
        ) in {"weather_now", "weather_7d"}:
            return self._weather.format_invocation(arguments)
        return None

    def collect_invocation_args(
        self,
        user_text: str,
        capability_id: str = "",
        initial_args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._weather.collect_invocation_args(
            user_text,
            capability_id=capability_id,
            initial_args=dict(initial_args or {}),
        )

    def resolve_access_control(
        self,
        context=None,
        *,
        invoked_tool: str = "",
        invoked_alias: str = "",
        args: str = "",
    ):
        if str(invoked_tool or "") in WEATHER_TOOLS or str(invoked_alias or "") in WEATHER_ALIASES:
            return getattr(self._weather, "access_control", None)
        return getattr(self, "access_control", None)

    def should_handle_direct(self, text: str, context: dict, key: str) -> bool:
        if str(key or "") in WEATHER_ALIASES:
            return self._weather.should_handle_direct(text, context, key)
        return True

    async def start(self, ctx: Optional[Dict[str, Any]] = None):
        await super().start(ctx)
        await start_inners([self._weather], ctx)

    async def stop(self):
        await super().stop()
        await stop_inners([self._weather])

    async def run(self, args, ctx):
        tool = str((ctx or {}).get("invoked_tool") or "")
        alias = str((ctx or {}).get("invoked_alias") or "")
        text = str(args or "").strip()
        if tool in WEATHER_TOOLS or alias in WEATHER_ALIASES:
            return await self._weather.run(args, ctx)
        if any(text.startswith(prefix) for prefix in WEATHER_ALIASES):
            return await self._weather.run(args, ctx)
        return await super().run(args, ctx)
