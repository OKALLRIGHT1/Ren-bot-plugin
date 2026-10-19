import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger
from services.info_sources.daily_cache import DailyInfoCache
from services.info_sources.providers.alapi import AlapiProvider
from services.info_sources.providers.anilist import AnilistAnimeProvider
from plugins.plugin_utils import handle_plugin_errors
from services.info_sources.service import InfoSourceService

from .api import BGMAPI, BilibiliAPI, ITHomeRSS
from .constants import (
    DEFAULT_SECTIONS,
    EMPTY_HITOKOTO,
    GREETING_STYLES,
    QQ_SOURCES,
    SECTION_KEYS,
)
from .api.date_utils import get_current_date_info, set_alapi_token
from .render import RenderService

logger = get_logger()

HOLIDAY_DISPLAY_MAX_DAYS = 14


class Plugin:
    def __init__(self):
        base_dir = Path(__file__).resolve().parent
        self._plugin_dir = base_dir.parent
        self._root_dir = self._plugin_dir.parents[1]
        self._config_path = self._plugin_dir / "config.json"
        self._data_dir = self._root_dir / "data" / "magic_girl_daily"
        self._mapping_path = self._data_dir / "group_mapping.json"

        self._config: Dict[str, Any] = {}
        self._settings: Dict[str, Any] = {}
        self._http_session: Optional["aiohttp.ClientSession"] = None
        self._push_task: Optional[asyncio.Task] = None
        self._gateway = None
        self._render_lock: Optional[asyncio.Lock] = None
        self._group_mapping: Dict[str, str] = {}
        self._renderer = RenderService(self._plugin_dir, {}, logger)
        self._last_push_date: Optional[str] = None  # 记录上一次自动推送的日期

        self.reload_config()
        self._load_group_mapping()

    def reload_config(self):
        try:
            self._config = json.loads(self._config_path.read_text(encoding="utf-8-sig"))
        except Exception:
            self._config = {}

        runtime_settings = getattr(self, "settings", None)
        settings = (
            runtime_settings
            if isinstance(runtime_settings, dict) and runtime_settings
            else (self._config.get("settings") or {})
        )
        self._settings = {
            "api_token": str(self._read_setting(settings, "api_token", "")).strip(),
            "max_anime_count": self._to_int(
                self._read_setting(settings, "max_anime_count", 4), 4, 1, 12
            ),
            "max_news_count": self._to_int(
                self._read_setting(settings, "max_news_count", 5), 5, 1, 12
            ),
            "max_hotword_count": self._to_int(
                self._read_setting(settings, "max_hotword_count", 4), 4, 1, 10
            ),
            "max_holiday_count": self._to_int(
                self._read_setting(settings, "max_holiday_count", 3), 3, 1, 8
            ),
            "render_mode": str(
                self._read_setting(settings, "render_mode", "image") or "image"
            )
            .strip()
            .lower(),
            "render_dpr": self._to_int(
                self._read_setting(settings, "render_dpr", 4), 4, 1, 6
            ),
            "enable_scheduled_push": self._to_bool(
                self._read_setting(settings, "enable_scheduled_push", False)
            ),
            "scheduled_push_time": str(
                self._read_setting(settings, "scheduled_push_time", "08:00") or "08:00"
            ).strip(),
            "scheduled_push_targets": self._normalize_targets(
                self._read_setting(settings, "scheduled_push_targets", [])
            ),
            "enable_ai_greeting": self._to_bool(
                self._read_setting(settings, "enable_ai_greeting", False)
            ),
            "title": str(self._read_setting(settings, "title", "") or "").strip(),
            "title_en": str(self._read_setting(settings, "title_en", "") or "").strip(),
            "header_image": str(self._read_setting(settings, "header_image", "") or "").strip(),
            "greeting_style": self._normalize_greeting_style(
                self._read_setting(settings, "greeting_style", "character")
            ),
            "custom_greeting": str(
                self._read_setting(settings, "custom_greeting", "") or ""
            ).strip(),
            "footer": str(self._read_setting(settings, "footer", "") or "").strip(),
            "sections": self._normalize_sections(
                self._read_setting(settings, "sections", DEFAULT_SECTIONS)
            ),
            "output_dir": str(
                self._read_setting(settings, "output_dir", "output/daily_reports")
                or "output/daily_reports"
            ),
        }
        self._renderer.update_settings(self._settings)
        set_alapi_token(self._settings.get("api_token", ""))

    def _read_setting(self, settings: Dict[str, Any], key: str, default: Any) -> Any:
        value = settings.get(key, default)
        if isinstance(value, dict):
            return value.get("default", default)
        return default if value is None else value

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(value)

    def _to_int(self, value: Any, default: int, min_val: int, max_val: int) -> int:
        try:
            num = int(value)
        except Exception:
            num = default
        return max(min_val, min(max_val, num))

    def _normalize_targets(self, raw: Any) -> List[str]:
        if isinstance(raw, dict):
            raw = raw.get("default", [])
        if raw is None:
            return []
        if not isinstance(raw, list):
            raw = [raw]
        return [str(item).strip() for item in raw if str(item).strip()]

    def _normalize_greeting_style(self, raw: Any) -> str:
        text = str(raw or "").strip().lower()
        if text in GREETING_STYLES:
            return text
        return "character"

    def _normalize_sections(self, raw: Any) -> List[str]:
        if isinstance(raw, dict):
            raw = raw.get("default", DEFAULT_SECTIONS)
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.replace("，", ",").split(",")]
        if not isinstance(raw, list):
            raw = list(DEFAULT_SECTIONS)
        seen = set()
        sections: List[str] = []
        for item in raw:
            key = str(item or "").strip().lower()
            if key not in SECTION_KEYS or key in seen:
                continue
            seen.add(key)
            sections.append(key)
        return sections or list(DEFAULT_SECTIONS)

    def _existing_path(self, raw: str) -> Optional[Path]:
        text = str(raw or "").strip()
        if not text or text.lower().startswith(("http://", "https://", "data:")):
            return None
        path = Path(text)
        candidates = [path] if path.is_absolute() else [
            Path.cwd() / path,
            self._root_dir / path,
            self._plugin_dir / path,
        ]
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _active_character(self) -> Dict[str, Any]:
        try:
            from modules.character_manager import character_manager

            return character_manager.get_active_character() or {}
        except Exception:
            return {}

    def _character_face_path(self, character: Dict[str, Any]) -> str:
        current_costume = ""
        try:
            from modules.character_manager import character_manager

            active_id = character_manager.data.get("active_id")
            current_costume = character_manager.get_current_costume_name(active_id) or ""
        except Exception:
            current_costume = ""
        costumes = character.get("costumes") or {}
        costume_cfg = (
            costumes.get(current_costume)
            if isinstance(costumes.get(current_costume), dict)
            else {}
        )
        for badge in (costume_cfg.get("assistant_badge"), character.get("assistant_badge")):
            if not isinstance(badge, dict):
                continue
            path = self._existing_path(str(badge.get("path") or ""))
            if path is not None:
                return str(path)
        qq_profile = character.get("qq_profile") if isinstance(character.get("qq_profile"), dict) else {}
        for key in ("avatar_path", "avatar", "avatar_url", "avatar_file"):
            path = self._existing_path(str(qq_profile.get(key) or ""))
            if path is not None:
                return str(path)
        path = self._existing_path(str(character.get("avatar") or ""))
        return str(path) if path is not None else ""

    def _resolve_presentation(self) -> Dict[str, Any]:
        character = self._active_character()
        name = str(character.get("name") or "").strip() or "助手"
        title = str(self._settings.get("title") or "").strip() or f"{name}日报"
        title_en = str(self._settings.get("title_en") or "").strip() or "DAILY REPORT"
        footer = str(self._settings.get("footer") or "").strip() or title_en
        header_setting = str(self._settings.get("header_image") or "").strip()
        if header_setting:
            header_path = self._existing_path(header_setting)
            header_image = str(header_path) if header_path is not None else ""
        else:
            header_image = self._character_face_path(character)
        if not header_image:
            fallback = self._plugin_dir / "res" / "image" / "2.no-bg.png"
            if fallback.exists():
                header_image = str(fallback)
        prompt = str(character.get("prompt") or "").strip()
        return {
            "character_name": name,
            "character_prompt": prompt[:240],
            "title": title,
            "title_en": title_en,
            "footer": footer,
            "header_image": header_image,
            "sections": list(self._settings.get("sections") or DEFAULT_SECTIONS),
            "greeting_style": self._settings.get("greeting_style") or "character",
            "custom_greeting": str(self._settings.get("custom_greeting") or "").strip(),
        }

    def _ensure_render_lock(self):
        if self._render_lock is None:
            self._render_lock = asyncio.Lock()

    def _is_qq_context(self, ctx: Optional[Dict[str, Any]]) -> bool:
        source = str((ctx or {}).get("source") or "").strip().lower()
        return source in QQ_SOURCES

    def _capture_context(self, ctx: Optional[Dict[str, Any]]):
        if not isinstance(ctx, dict):
            return
        from services.plugin_ports import resolve_gateway

        gateway = resolve_gateway(ctx)
        if gateway is not None:
            self._gateway = gateway

    def _extract_session_info(
        self, ctx: Optional[Dict[str, Any]]
    ) -> Tuple[str, str, str]:
        if not isinstance(ctx, dict):
            return "", "", ""
        channel_meta = ctx.get("channel_meta") or {}
        session_id = str(channel_meta.get("session_id") or "").strip()
        group_id = str(channel_meta.get("group_id") or "").strip()
        user_id = str(channel_meta.get("user_id") or "").strip()
        if not group_id and session_id.startswith("group:"):
            group_id = session_id.split(":", 1)[1].strip()
        return session_id, group_id, user_id

    def _learn_group_mapping(self, ctx: Optional[Dict[str, Any]]):
        if not self._is_qq_context(ctx):
            return
        session_id, group_id, _ = self._extract_session_info(ctx)
        if not group_id or not session_id:
            return
        if self._group_mapping.get(group_id) == session_id:
            return
        self._group_mapping[group_id] = session_id
        self._save_group_mapping()

    def _load_group_mapping(self):
        try:
            if self._mapping_path.exists():
                self._group_mapping = json.loads(
                    self._mapping_path.read_text(encoding="utf-8")
                )
        except Exception as exc:
            logger.warning(f"加载群组映射失败: {exc}")
            self._group_mapping = {}

    def _save_group_mapping(self):
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._mapping_path.write_text(
                json.dumps(self._group_mapping, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"保存群组映射失败: {exc}")

    async def start(self, ctx: Optional[Dict[str, Any]] = None):
        self._capture_context(ctx)
        if self._settings.get("enable_scheduled_push"):
            await self._ensure_scheduler()

    async def stop(self):
        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        await self._close_http_session()

    async def terminate(self):
        await self.stop()

    async def _ensure_http_session(self) -> Optional["aiohttp.ClientSession"]:
        if aiohttp is None:
            return None
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _close_http_session(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    def _missing_image_deps(self) -> List[str]:
        if self._renderer is None:
            return []
        return self._renderer.missing_image_deps()

    def _can_render_image(self) -> bool:
        if self._renderer is None:
            return False
        return self._renderer.can_render_image()

    def _build_missing_deps_note(self) -> str:
        missing = self._missing_image_deps()
        if missing:
            return f"⚠️ 缺少依赖 {', '.join(missing)}，已返回文字版日报。"
        return "⚠️ 图片模式不可用，已返回文字版日报。"

    def _empty_direct_reply(self) -> str:
        return ""

    async def _build_report_data(self) -> Dict[str, Any]:
        date_info = await asyncio.to_thread(get_current_date_info)
        max_anime_count = int(self._settings.get("max_anime_count", 4))
        max_news_count = int(self._settings.get("max_news_count", 5))
        max_hotword_count = int(self._settings.get("max_hotword_count", 4))
        max_holiday_count = int(self._settings.get("max_holiday_count", 3))

        (
            anime_list,
            bili_hotwords,
            hitokoto_data,
            moyu_list,
            world_news,
            it_news,
        ) = await self._fetch_all_data(
            max_anime_count=max_anime_count,
            max_news_count=max_news_count,
            max_hotword_count=max_hotword_count,
            max_holiday_count=max_holiday_count,
        )

        hitokoto_data = self._normalize_hitokoto(hitokoto_data)
        presentation = self._resolve_presentation()
        sections = presentation["sections"]

        return {
            "date_info": date_info,
            "anime_list": anime_list or [] if "today_anime" in sections else [],
            "bili_hotwords": bili_hotwords or [] if "bili_hot" in sections else [],
            "hitokoto_data": hitokoto_data if "hitokoto" in sections else dict(EMPTY_HITOKOTO),
            "moyu_list": self._filter_display_holidays(moyu_list) if "moyu" in sections else [],
            "world_news": world_news or [] if "world_news" in sections else [],
            "it_news": it_news or [] if "it_news" in sections else [],
            "presentation": presentation,
        }

    def _filter_display_holidays(self, moyu_list: Any) -> List[Dict[str, Any]]:
        if not isinstance(moyu_list, list):
            return []

        display_items: List[Dict[str, Any]] = []
        for item in moyu_list:
            if not isinstance(item, dict):
                continue
            try:
                days_left = int(str(item.get("days_left", "")).strip())
            except (TypeError, ValueError):
                continue
            if 0 <= days_left <= HOLIDAY_DISPLAY_MAX_DAYS:
                display_items.append(item)
        return display_items

    def _normalize_hitokoto(self, hitokoto_data: Any) -> Dict[str, str]:
        if not isinstance(hitokoto_data, dict):
            return dict(EMPTY_HITOKOTO)
        text = str(hitokoto_data.get("hitokoto") or "").strip()
        from_value = str(hitokoto_data.get("from") or "").strip()
        if from_value == "网络":
            from_value = "佚名"
        if not text:
            return dict(EMPTY_HITOKOTO)
        return {"hitokoto": text, "from": from_value}

    async def _fetch_all_data(
        self,
        max_anime_count: int,
        max_news_count: int,
        max_hotword_count: int,
        max_holiday_count: int,
    ) -> Tuple[List[Dict], List[str], Dict[str, str], List[Dict], List[str], List[str]]:
        empty = (
            [],
            [],
            dict(EMPTY_HITOKOTO),
            [],
            [],
            [],
        )
        if aiohttp is None:
            return empty

        session = await self._ensure_http_session()
        if session is None:
            return empty

        api_token = self._settings.get("api_token", "")
        bgm_api = BGMAPI(session=session)
        bili_api = BilibiliAPI(session=session)
        ithome_rss = ITHomeRSS(session=session)
        anime_cache = DailyInfoCache(self._root_dir / "data" / "info_sources" / "cache")
        anilist_provider = AnilistAnimeProvider()
        alapi_provider = AlapiProvider(
            endpoint_dir=self._root_dir / "data" / "info_sources" / "alapi",
            token_getter=lambda: api_token,
        )

        async def fetch_source_once(name: str, fetch_raw, parse_raw):
            try:
                raw_data = await fetch_raw()
                if raw_data is None:
                    logger.warning(f"{name} 数据源请求无数据")
                    return None
                return parse_raw(raw_data)
            except Exception as exc:
                logger.warning(f"{name} 数据源请求失败: {exc}")
                return None

        async def fetch_today_anime(limit: int = 4):
            cached = anime_cache.read_today("today_anime")
            if isinstance(cached, list) and cached:
                logger.info("today_anime source=cache date=today")
                return cached[:limit]

            bgm_result = await fetch_source_once(
                "BGM 新番",
                bgm_api.get_calendar_async,
                lambda data: bgm_api.parse_today_anime(
                    data, limit, use_fallback=False
                ),
            )
            if bgm_result:
                anime_cache.write_today("today_anime", bgm_result)
                logger.info("today_anime source=bangumi")
                return bgm_result

            anilist_result = await anilist_provider.fetch("today_anime", limit=limit)
            if anilist_result.ok and anilist_result.data:
                anime_cache.write_today("today_anime", anilist_result.data)
                logger.info("today_anime source=anilist")
                return anilist_result.data

            logger.warning("today_anime unavailable from bangumi and anilist")
            return None

        async def fetch_bili_hot(limit: int = 4):
            return await fetch_source_once(
                "B站热点",
                bili_api.get_hotwords_data_async,
                lambda data: bili_api.parse_hotwords_data(data, limit),
            )

        async def fetch_it_news(limit: int = 5):
            return await fetch_source_once(
                "IT资讯",
                ithome_rss.get_rss_async,
                lambda data: ithome_rss.parse_news(data, limit),
            )

        service = InfoSourceService(
            token_getter=lambda: api_token,
            alapi_provider=alapi_provider,
            endpoint_dir=self._root_dir / "data" / "info_sources" / "alapi",
            builtin_fetchers={
                "today_anime": fetch_today_anime,
                "bili_hot": fetch_bili_hot,
                "it_news": fetch_it_news,
            },
            daily_fallbacks={
                "today_anime": [],
                "bili_hot": [],
                "hitokoto": dict(EMPTY_HITOKOTO),
                "moyu": [],
                "world_news": [],
                "it_news": [],
            },
        )
        bundle = await service.fetch_daily_bundle(
            max_anime_count=max_anime_count,
            max_news_count=max_news_count,
            max_hotword_count=max_hotword_count,
            max_holiday_count=max_holiday_count,
        )

        return (
            bundle["anime_list"],
            bundle["bili_hotwords"],
            bundle["hitokoto_data"],
            bundle["moyu_list"],
            bundle["world_news"],
            bundle["it_news"],
        )

    def _format_text_report(self, report_data: Dict[str, Any], note: str = "") -> str:
        date_info = report_data.get("date_info") or {}
        presentation = report_data.get("presentation") or self._resolve_presentation()
        title = str(presentation.get("title") or "日报")
        header = f"📰 {title} {date_info.get('date_str', '')} {date_info.get('week_cn', '')}"
        cn_date = date_info.get("cn_date_str")
        if cn_date:
            header += f"（{cn_date}）"

        lines: List[str] = []
        if note:
            lines.append(note)
        lines.append(header)
        lines.append("")

        section_renderers = {
            "moyu": self._format_moyu_section,
            "bili_hot": self._format_bili_section,
            "today_anime": self._format_anime_section,
            "world_news": self._format_world_news_section,
            "it_news": self._format_it_news_section,
            "hitokoto": self._format_hitokoto_section,
        }
        for key in presentation.get("sections") or DEFAULT_SECTIONS:
            renderer = section_renderers.get(key)
            if renderer is None:
                continue
            block = renderer(report_data)
            if block:
                lines.append(block)
                lines.append("")

        return "\n".join(line for line in lines if line is not None).strip()

    def _format_moyu_section(self, report_data: Dict[str, Any]) -> str:
        moyu_list = report_data.get("moyu_list") or []
        if not moyu_list:
            return ""
        lines = ["【摸鱼日历】"]
        for item in moyu_list:
            name = str(item.get("name") or "").strip()
            days_left = str(item.get("days_left") or "").strip()
            if name:
                lines.append(f"- 距离 {name} 还有 {days_left} 天")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_bili_section(self, report_data: Dict[str, Any]) -> str:
        bili_hotwords = report_data.get("bili_hotwords") or []
        if not bili_hotwords:
            return ""
        lines = ["【B站热点】"]
        for idx, hot in enumerate(bili_hotwords, 1):
            lines.append(f"{idx}. {hot}")
        return "\n".join(lines)

    def _format_anime_section(self, report_data: Dict[str, Any]) -> str:
        anime_list = report_data.get("anime_list") or []
        if not anime_list:
            return ""
        lines = ["【今日新番】"]
        for item in anime_list:
            title = str(item.get("title") or "").strip()
            if title:
                lines.append(f"- {title}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_world_news_section(self, report_data: Dict[str, Any]) -> str:
        world_news = report_data.get("world_news") or []
        if not world_news:
            return ""
        lines = ["【世界新闻】"]
        for news in world_news:
            lines.append(f"- {news}")
        return "\n".join(lines)

    def _format_it_news_section(self, report_data: Dict[str, Any]) -> str:
        it_news = report_data.get("it_news") or []
        if not it_news:
            return ""
        lines = ["【科技资讯】"]
        for news in it_news:
            lines.append(f"- {news}")
        return "\n".join(lines)

    def _format_hitokoto_section(self, report_data: Dict[str, Any]) -> str:
        hitokoto = report_data.get("hitokoto_data") or {}
        hitokoto_text = str(hitokoto.get("hitokoto") or "").strip()
        hitokoto_from = str(hitokoto.get("from") or "").strip()
        if not hitokoto_text:
            return ""
        lines = ["【今日一言】"]
        if hitokoto_from:
            lines.append(f"“{hitokoto_text}” —— {hitokoto_from}")
        else:
            lines.append(f"“{hitokoto_text}”")
        return "\n".join(lines)

    def _build_output_path(self) -> Path:
        output_dir = Path(self._settings.get("output_dir") or "output/daily_reports")
        if not output_dir.is_absolute():
            output_dir = self._root_dir / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"magic_girl_daily_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        return output_dir / filename

    def _build_temp_image_path(self) -> Path:
        temp_dir = Path(tempfile.gettempdir())
        filename = f"magic_girl_daily_{os.getpid()}_{uuid.uuid4().hex[:6]}.png"
        return temp_dir / filename

    async def _render_image(
        self, report_data: Dict[str, Any], output_path: Optional[Path] = None
    ) -> str:
        if self._renderer is None:
            raise RuntimeError("renderer not initialized")
        return await self._renderer.render_image(report_data, output_path=output_path)

    async def _generate_greeting_text(self, report_data: Dict[str, Any]) -> str:
        presentation = report_data.get("presentation") or self._resolve_presentation()
        style = str(presentation.get("greeting_style") or "character")
        if style == "off":
            return ""
        if style == "custom":
            custom = str(presentation.get("custom_greeting") or "").strip()
            if custom:
                return "📰 " + custom.format(
                    name=presentation.get("character_name") or "助手",
                    title=presentation.get("title") or "日报",
                )
            return self._get_default_greeting(report_data, presentation)
        if not self._settings.get("enable_ai_greeting", False):
            return self._get_default_greeting(report_data, presentation)

        try:
            from modules.llm import chat_with_ai
        except Exception:
            return self._get_default_greeting(report_data, presentation)

        date_info = report_data.get("date_info") or {}
        now = datetime.now()
        prompt_parts = [
            f"现在是 {date_info.get('date_str', '')} {date_info.get('week_cn', '')}",
            f"时间是 {now.hour} 点",
        ]
        cn_date = date_info.get("cn_date_str")
        if cn_date and cn_date != "农历未知":
            prompt_parts.append(f"农历 {cn_date}")

        moyu_list = report_data.get("moyu_list") or []
        if moyu_list:
            holiday_names = [item.get("name") for item in moyu_list if item.get("name")]
            if holiday_names:
                prompt_parts.append(f"即将到来的节日：{', '.join(holiday_names[:2])}")

        name = presentation.get("character_name") or "助手"
        title = presentation.get("title") or "日报"
        persona = presentation.get("character_prompt") or ""
        prompt = (
            f"{', '.join(prompt_parts)}。"
            f"请用当前角色「{name}」的口吻，为「{title}」写一句不超过 15 字的推送问候。"
            "结合时间或节日，只返回问候语文本，不要引号。"
        )
        system = f"你是{name}，正在推送今日{title}。语言简短，保持角色语气。"
        if persona:
            system += f"\n角色设定摘要：{persona}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        try:
            reply = await asyncio.to_thread(
                chat_with_ai, messages, "default", "magic_girl_daily"
            )
        except Exception:
            return self._get_default_greeting(report_data, presentation)

        greeting = str(reply or "").strip().strip("\"'“”")
        if not greeting:
            return self._get_default_greeting(report_data, presentation)
        if len(greeting) > 50:
            greeting = greeting[:50]
        return f"📰 {greeting}"

    def _get_default_greeting(
        self, report_data: Dict[str, Any], presentation: Optional[Dict[str, Any]] = None
    ) -> str:
        presentation = presentation or report_data.get("presentation") or self._resolve_presentation()
        name = str(presentation.get("character_name") or "助手")
        title = str(presentation.get("title") or "日报")
        hour = datetime.now().hour
        if 5 <= hour < 11:
            period = "早上好"
        elif 11 <= hour < 14:
            period = "中午好"
        elif 14 <= hour < 18:
            period = "下午好"
        else:
            period = "晚上好"

        moyu_list = report_data.get("moyu_list") or []
        if moyu_list:
            holiday = moyu_list[0]
            holiday_name = holiday.get("name")
            days_left = str(holiday.get("days_left") or "")
            if holiday_name and days_left.isdigit():
                days_int = int(days_left)
                if days_int == 0:
                    return f"📰 {name}：{holiday_name}快乐，{title}来了。"
                if days_int <= 3:
                    return f"📰 {name}：距离{holiday_name}还有{days_int}天。"

        return f"📰 {name}：{period}，今日{title}。"

    def _looks_like_group_id_request(self, text: str) -> bool:
        t = str(text or "").strip().lower()
        return (
            "群组id" in t
            or "群id" in t
            or "会话id" in t
            or "session_id" in t
            or "session id" in t
            or "群号" in t
        )

    def _format_group_id_reply(self, ctx: Optional[Dict[str, Any]]) -> str:
        if not self._is_qq_context(ctx):
            return "该功能仅在 QQ 会话中可用。"
        session_id, group_id, _ = self._extract_session_info(ctx)
        if not session_id:
            return "未检测到 session_id，请确认当前为 QQ 会话。"
        lines = [f"📋 当前会话ID：{session_id}"]
        if group_id:
            lines.append(f"群号：{group_id}")
        lines.append("可将会话ID填入 scheduled_push_targets 进行定时推送。")
        return "\n".join(lines)

    def _normalize_target(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        if ":" in text:
            prefix, rest = text.split(":", 1)
            prefix = prefix.strip().lower()
            rest = rest.strip()
            if prefix in {"group", "private"} and rest.isdigit():
                return f"{prefix}:{rest}"
            return text
        if text.isdigit():
            return f"group:{text}"
        return ""

    def _parse_push_time(self, text: str) -> dt_time:
        try:
            hour, minute = map(int, str(text or "").strip().split(":", 1))
            return dt_time(hour, minute)
        except Exception:
            return dt_time(8, 0)

    async def _ensure_scheduler(self):
        if self._push_task and not self._push_task.done():
            return
        self._push_task = asyncio.create_task(self._scheduled_push_loop())

    async def _scheduled_push_loop(self):
        while True:
            try:
                push_time = self._parse_push_time(
                    self._settings.get("scheduled_push_time", "08:00")
                )
                now = datetime.now()
                next_push = datetime.combine(now.date(), push_time)
                
                # 如果当前时间超过推送时间，或者今天已经推过了，则安排在明天
                if next_push <= now or self._last_push_date == now.date().isoformat():
                    next_push += timedelta(days=1)
                    
                wait_seconds = (next_push - now).total_seconds()
                logger.info(f"定时推送任务等待下一次执行: {next_push}")
                
                await asyncio.sleep(wait_seconds)
                
                # 检查是否由于系统定时器精度问题过早唤醒（相差大于1秒）
                wake_now = datetime.now()
                if wake_now < next_push and (next_push - wake_now).total_seconds() > 1.0:
                    continue
                    
                await self._push_daily_to_targets()
                
                # 记录本次推送日期
                self._last_push_date = wake_now.date().isoformat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"定时推送任务异常: {exc}", exc_info=True)
                await asyncio.sleep(3600)

    async def _push_daily_to_targets(self):
        targets = self._settings.get("scheduled_push_targets") or []
        if not targets:
            logger.warning("定时推送已启用，但未配置目标会话，已跳过")
            return "定时推送已启用，但未配置目标会话。"
        gateway = self._gateway
        if gateway is None or not gateway.available():
            logger.warning("定时推送缺少 gateway，上下文未就绪")
            return "当前 gateway 未就绪，无法推送日报。"

        report_data = await self._build_report_data()
        render_mode = str(self._settings.get("render_mode", "image")).lower()

        image_path: Optional[str] = None
        text_report: Optional[str] = None
        greeting = ""

        if render_mode == "image" and self._can_render_image():
            try:
                image_path = await self._render_image(
                    report_data, output_path=self._build_temp_image_path()
                )
                greeting = await self._generate_greeting_text(report_data)
            except Exception as exc:
                logger.error(f"定时推送生成图片失败: {exc}", exc_info=True)

        if not image_path:
            note = self._build_missing_deps_note()
            text_report = self._format_text_report(report_data, note=note)

        # 先标准化再去重，避免 "123456" 与 "group:123456" 发到同一会话两次。
        unique_targets = list(
            dict.fromkeys(
                session_id
                for session_id in (self._normalize_target(raw) for raw in targets)
                if session_id
            )
        )
        sent_any = False

        for session_id in unique_targets:
            sent_any = True
            ctx = {
                "source": "qq_gateway",
                "channel_meta": {"session_id": session_id, "adapter": "napcat_qq"},
            }
            if image_path:
                ok = await gateway.send_image(image_path, ctx, caption=greeting)
                if not ok:
                    logger.warning(f"日报图片推送可能失败，已避免补发文字版: {session_id}")
            else:
                await gateway.send_text(
                    text_report or "日报生成失败。", ctx, emotion="neutral"
                )

        if image_path:
            asyncio.create_task(self._cleanup_file(image_path, delay=45))
        return "" if sent_any else "未识别到有效推送目标。"

    async def _push_daily_to_session(self, session_id: str):
        session_id = self._normalize_target(session_id)
        if not session_id:
            return "未识别到有效会话ID。"
        gateway = self._gateway
        if gateway is None or not gateway.available():
            return "当前 gateway 未就绪，无法测试推送。"

        report_data = await self._build_report_data()
        render_mode = str(self._settings.get("render_mode", "image")).lower()
        image_path: Optional[str] = None
        text_report: Optional[str] = None
        greeting = ""

        if render_mode == "image" and self._can_render_image():
            try:
                image_path = await self._render_image(
                    report_data, output_path=self._build_temp_image_path()
                )
                greeting = await self._generate_greeting_text(report_data)
            except Exception as exc:
                logger.error(f"测试推送生成图片失败: {exc}", exc_info=True)

        if not image_path:
            note = self._build_missing_deps_note()
            text_report = self._format_text_report(report_data, note=note)

        ctx = {
            "source": "qq_gateway",
            "channel_meta": {"session_id": session_id, "adapter": "napcat_qq"},
        }
        if image_path:
            ok = await gateway.send_image(image_path, ctx, caption=greeting)
            if image_path:
                asyncio.create_task(self._cleanup_file(image_path, delay=45))
            if ok:
                return ""
            logger.warning(f"日报图片测试推送可能失败，已避免补发文字版: {session_id}")
            return ""
        await gateway.send_text(
            text_report or "日报生成失败。", ctx, emotion="neutral"
        )
        return ""

    async def _cleanup_file(self, path: str, delay: float = 45.0):
        if not path:
            return
        try:
            await asyncio.sleep(max(0.0, float(delay)))
        except Exception:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    @handle_plugin_errors("日报")
    async def run(self, args, ctx):
        self._capture_context(ctx)
        self._learn_group_mapping(ctx)

        text = str(args or "").strip()
        if self._looks_like_group_id_request(text):
            return self._format_group_id_reply(ctx)

        if "测试推送" in text or "立即推送" in text:
            result = await self._push_daily_to_targets()
            return result or self._empty_direct_reply()

        if "测试当前" in text:
            session_id, _, _ = self._extract_session_info(ctx)
            if not session_id:
                return "当前会话未识别到 session_id，无法测试当前会话推送。"
            result = await self._push_daily_to_session(session_id)
            return result or self._empty_direct_reply()

        if self._settings.get("enable_scheduled_push"):
            await self._ensure_scheduler()

        self._ensure_render_lock()
        if self._render_lock is None:
            return "⚠️ 渲染锁初始化失败。"
        async with self._render_lock:
            report_data = await self._build_report_data()
            render_mode = str(self._settings.get("render_mode", "image")).lower()

            if render_mode == "text":
                return self._format_text_report(report_data)

            if not self._can_render_image():
                note = self._build_missing_deps_note()
                return self._format_text_report(report_data, note=note)

            is_qq = self._is_qq_context(ctx)
            output_path = (
                self._build_temp_image_path() if is_qq else self._build_output_path()
            )

            try:
                image_path = await self._render_image(
                    report_data, output_path=output_path
                )
            except Exception as exc:
                logger.error(f"日报图片渲染失败: {exc}", exc_info=True)
                note = "⚠️ 图片渲染失败，已返回文字版日报。"
                return self._format_text_report(report_data, note=note)

            if is_qq:
                caption = await self._generate_greeting_text(report_data)
                title = (report_data.get("presentation") or {}).get("title") or "日报"
                return {
                    "__type__": "gateway_image",
                    "image_path": image_path,
                    "caption": caption,
                    "success_text": f"📰 {title}已发送。",
                    "fallback_text": "⚠️ 日报图片已生成，但发送失败。",
                    "suppress_fallback_reply": True,
                }

            title = (report_data.get("presentation") or {}).get("title") or "日报"
            return f"📰 {title}已生成：{image_path}"
