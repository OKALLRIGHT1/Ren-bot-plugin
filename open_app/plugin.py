import os
import subprocess
from typing import Any, Dict, Optional

from core.logger import get_logger
from plugins.plugin_utils import handle_plugin_errors

logger = get_logger()


class Plugin:
    """Launch apps from a configured trust list (aliases → paths)."""

    name = "快速启动"
    type = "direct"
    gated_action = "system.spawn_process_trusted"

    def get_tool_schema(self):
        return {
            "name": "open_app",
            "description": "打开信任列表里的本地应用，例如计算器、记事本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "应用显示名，必须在信任列表中",
                    }
                },
                "required": ["query"],
            },
        }

    def format_invocation(self, arguments):
        args = dict(arguments or {})
        return str(args.get("query") or args.get("text") or "").strip()

    def __init__(self):
        self.app_map: Dict[str, Any] = {}
        self._load_app_config()

    def _load_app_config(self):
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(config_path):
                import json

                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                settings = config.get("settings", {})
                app_list = settings.get("app_list", {}).get("default", [])
                self.load_app_list(app_list)
                logger.info(f"从配置加载了 {len(self.app_map)} 个应用")
        except Exception as e:
            logger.error(f"加载应用配置失败: {e}")
            self.app_map = {
                "计算器": "calc.exe",
                "记事本": "notepad.exe",
                "画图": "mspaint.exe",
            }

    def load_app_list(self, app_list):
        self.app_map = {}
        for item in app_list or []:
            if "|" not in str(item):
                continue
            parts = str(item).split("|", 1)
            if len(parts) != 2:
                continue
            display_name, path = parts
            display_name = display_name.strip()
            path = path.strip()
            if not display_name or not path:
                continue
            if "||" in path:
                self.app_map[display_name] = [p.strip() for p in path.split("||")]
            else:
                self.app_map[display_name] = path

    def reload_config(self):
        logger.info("重新加载应用配置...")
        self._load_app_config()

    def _match_target(self, app_name: str) -> Optional[str]:
        app_l = str(app_name or "").strip().lower()
        for key, paths in self.app_map.items():
            key_l = str(key or "").strip().lower()
            if not key_l or (key_l not in app_l and key not in str(app_name or "")):
                continue
            if isinstance(paths, list):
                for p in paths:
                    if os.path.exists(p):
                        return p
            else:
                path_s = str(paths)
                if path_s.endswith(".exe") and os.path.sep not in path_s:
                    return path_s
                if os.path.exists(path_s):
                    return path_s
        return None

    def resolve_gated_action(self, args: str, ctx: Optional[Dict[str, Any]] = None) -> str:
        """Trust-list hits are LOW auto-confirm; unknown targets stay HIGH+confirm."""
        app_name = str(args or "").strip().lower()
        if self._match_target(app_name):
            return "system.spawn_process_trusted"
        return "system.spawn_process"

    @handle_plugin_errors("快速启动")
    async def run(self, args, ctx):
        app_name = str(args or "").strip().lower()
        target_path = self._match_target(app_name)

        logger.info(f"尝试启动应用: {app_name}")

        if not target_path:
            logger.warning(f"未找到应用: {args}")
            return (
                f"⚠️ 找不到应用 '{args}'，或不在信任列表中。\n"
                "💡 在插件自定义配置中添加：显示名|路径\n"
                "列表外路径不会直接启动（需确认策略，当前仅信任列表可启动）。"
            )

        try:
            subprocess.Popen(target_path)
            logger.info(f"成功启动应用: {app_name} path={target_path}")
            return f"✅ 已为你启动 {app_name}。"
        except (FileNotFoundError, PermissionError) as e:
            logger.error(f"启动应用失败(文件/权限): {app_name}, 错误: {e}")
            return f"❌ 启动失败，文件不存在或无权限: {e}"
        except Exception as e:
            logger.error(f"启动应用异常: {app_name}, 错误: {e}")
            return f"❌ 启动失败: {e}"
