"""QQ watermark-free media download.

Slash command runs immediately. A clear natural-language request only stores
a confirmation; the download starts after the user replies 确认.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.capability_manager import ToolCapability, ToolCapabilityMatch

from .xdownload import (
    IMAGE_EXTENSIONS,
    XDownloadClient,
    XDownloadError,
    user_message_for_error,
    validate_source_url,
)


COMMANDS = ("/去水印", "/提取", "/下载")
COMMAND = COMMANDS[0]
TRIGGER = "qq_watermark"
SECRET_KEY = "api_key"
CONFIRM_TTL_SEC = 180
CONFIRM_YES = {"确认", "确定", "好", "好的", "是", "yes", "ok"}
CONFIRM_NO = {"取消", "算了", "不用", "不要", "no"}
EXPLICIT_VERBS = (
    "去水印",
    "无水印",
    "解析下载",
    "解析这个",
    "解析一下",
    "提取图片",
    "提取视频",
    "提取这个",
    "提取链接",
    "下载图片",
    "下载视频",
    "下载原图",
    "下载这个",
    "保存原图",
    "保存视频",
)
HINT_VERBS = ("去水印", "无水印", "解析", "提取", "下载")
URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+", re.IGNORECASE)
IMAGE_SEND_LIMIT = 1

_PENDING: Dict[str, Dict[str, Any]] = {}
_HITS: Dict[str, List[float]] = {}


class Plugin:
    aliases = ["/去水印", "/提取", "/下载"]

    def __init__(self):
        self._config_path = Path(__file__).with_name("config.json")
        self._settings: Dict[str, Any] = {}
        self.reload_config()

    def reload_config(self):
        try:
            config = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}
        runtime = getattr(self, "settings", None)
        settings = runtime if isinstance(runtime, dict) and runtime else (config.get("settings") or {})
        self._settings = {
            "base_url": str(self._read(settings, "base_url", "https://dl.tomori.de5.net/") or ""),
            "api_key": str(self._read(settings, "api_key", "") or ""),
            "request_timeout_sec": self._read(settings, "request_timeout_sec", 180),
            "max_file_mb": self._read(settings, "max_file_mb", 80),
            "max_images": self._read(settings, "max_images", IMAGE_SEND_LIMIT),
            "rate_limit_per_min": self._read(settings, "rate_limit_per_min", 6),
        }

    @staticmethod
    def _read(settings: dict, key: str, default):
        value = settings.get(key, default)
        if isinstance(value, dict):
            return value.get("default", default)
        return value

    def get_tool_schema(self):
        return {
            "name": TRIGGER,
            "description": (
                "解析并去水印下载用户明确给出的一个公开平台链接，结果发回当前 QQ。"
                "仅在用户明确要求下载、解析、提取图片或去水印时使用；"
                "只是出现链接时不要调用。调用后仍需用户确认才会真正下载。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "用户给出的一个 http(s) 链接"},
                },
                "required": ["url"],
            },
        }

    def format_invocation(self, arguments):
        url = str((arguments or {}).get("url") or "").strip()
        return f"{COMMAND} {url}".strip()

    def get_capabilities(self):
        return [
            ToolCapability(
                id="qq_watermark.download_cmd",
                plugin=TRIGGER,
                trigger_mode="command_only",
                match=self._match_command,
                check_available=self._check_available,
                description="用 /去水印 下载无水印媒体",
                examples=["/去水印 https://v.douyin.com/xxxx/"],
            ),
            ToolCapability(
                id="qq_watermark.download",
                plugin=TRIGGER,
                trigger_mode="natural",
                match=self._match_natural,
                check_available=self._check_available,
                description="用户明确要求解析或去水印下载一个链接时，先确认再下载",
                examples=["帮我把这个抖音去水印下载下来 https://v.douyin.com/xxxx/"],
            ),
        ]

    def _check_available(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        self.reload_config()
        if self._api_key():
            return {"available": True}
        return {"available": False, "reason": "missing_secret: 未配置解析服务 API Key"}

    def should_handle_direct(self, user_text: str, context: dict, matched_alias: str) -> bool:
        return _split_command(user_text) is not None

    def _match_command(self, text: str, ctx: Dict[str, Any]) -> Optional[ToolCapabilityMatch]:
        raw = str(text or "").strip()
        if _split_command(raw) is None:
            return None
        return ToolCapabilityMatch(
            capability_id="qq_watermark.download_cmd",
            plugin=TRIGGER,
            score=1.0,
            args={"url": _first_url(raw)},
            raw_text=raw,
            reason="watermark_command",
        )

    def _match_natural(self, text: str, ctx: Dict[str, Any]) -> Optional[ToolCapabilityMatch]:
        raw = str(text or "").strip()
        if not raw or raw.startswith("/"):
            return None
        level = classify_natural(raw, ctx)
        if level != "explicit":
            return None
        url = _resolve_target_url(raw, ctx)
        if not url:
            return None
        return ToolCapabilityMatch(
            capability_id="qq_watermark.download",
            plugin=TRIGGER,
            score=0.9,
            args={"url": url, "confirm": True},
            raw_text=raw,
            reason="explicit_watermark_request",
        )

    def _api_key(self) -> str:
        return str(self._settings.get("api_key") or "").strip()

    @staticmethod
    def _log_failure(stage: str, exc: BaseException) -> None:
        code = getattr(exc, "code", "") or exc.__class__.__name__
        detail = str(exc).replace("\n", " ").strip()[:180]
        try:
            from core.logger import get_logger

            get_logger().warning(f"[qq_watermark] {stage} failed: {code} {detail}")
        except Exception:
            print(f"[qq_watermark] {stage} failed: {code} {detail}")

    def _client(self) -> XDownloadClient:
        max_mb = _bounded_int(self._settings.get("max_file_mb"), 80, 1, 200)
        timeout = _bounded_int(self._settings.get("request_timeout_sec"), 180, 10, 300)
        return XDownloadClient(
            base_url=str(self._settings.get("base_url") or ""),
            api_key=self._api_key(),
            timeout_sec=timeout,
            max_bytes=max_mb * 1024 * 1024,
        )

    def _is_qq(self, context: dict) -> bool:
        source = str((context or {}).get("source") or "").strip().lower()
        return source in {"qq_gateway", "napcat_qq"}

    async def run(self, args: str, context: dict):
        self.reload_config()
        if not self._is_qq(context):
            return "去水印目前只在 QQ 里使用。"
        text = str(args or "").strip()
        if _is_confirm_reply(text):
            return await self._consume_confirmation(text, context)
        if _split_command(text) is not None:
            return await self._run_command(text, context)
        url = _resolve_target_url(text, context)
        if not url:
            return "没有找到可解析的链接。把链接发在这句话里，或回复带链接的那条消息。"
        return self._stage_confirmation(url, context, source="natural")

    async def _run_command(self, text: str, context: dict):
        payload = _split_command(text) or ""
        urls = _all_urls(payload)
        if len(urls) > 1:
            return "一次只能处理一个链接，请只发一个。"
        if not urls:
            recovered = _context_urls(context)
            if len(recovered) > 1:
                return "这句话里没有链接，引用的消息里有多个链接。一次只能处理一个。"
            if not recovered:
                return _usage() if not payload else "没有找到链接。用法：/去水印 链接"
            urls = recovered
        try:
            validate_source_url(urls[0])
        except XDownloadError as exc:
            return user_message_for_error(exc)
        if not self._allow_rate(context):
            return "请求太频繁了，请稍后再试。"
        return await self._execute(urls[0], context)

    def _stage_confirmation(self, url: str, context: dict, *, source: str) -> str:
        try:
            clean = validate_source_url(url)
        except XDownloadError as exc:
            return user_message_for_error(exc)
        key = _session_key(context)
        _PENDING[key] = {"url": clean, "expires": time.monotonic() + CONFIRM_TTL_SEC, "source": source}
        return (
            "要我解析并去水印下载这个链接，然后发回这里吗？\n"
            f"{clean}\n"
            "回复「确认」开始，回复「取消」放弃。"
        )

    async def _consume_confirmation(self, text: str, context: dict) -> str:
        key = _session_key(context)
        pending = _PENDING.get(key)
        if not pending or float(pending.get("expires") or 0) < time.monotonic():
            _PENDING.pop(key, None)
            return "没有待确认的去水印请求。用法：/去水印 链接"
        word = _confirm_word(text)
        if word in CONFIRM_NO:
            _PENDING.pop(key, None)
            return "已取消。"
        if word not in CONFIRM_YES:
            return "请回复「确认」或「取消」。"
        _PENDING.pop(key, None)
        if not self._allow_rate(context):
            return "请求太频繁了，请稍后再试。"
        return await self._execute(str(pending.get("url") or ""), context)

    async def _execute(self, url: str, context: dict):
        if not self._api_key():
            return "解析服务还没配置密钥，请联系管理员。"
        client = self._client()
        try:
            parsed = await client.parse(url)
        except XDownloadError as cop:
            self._log_failure("parse", cop)
            return user_message_for_error(cop)
        except Exception as cop:
            self._log_failure("parse", cop)
            return user_message_for_error(XDownloadError("network", "network"))
        work = _work_dir()
        try:
            delivered = await self._deliver(client, parsed, url, context, work)
        except XDownloadError as cop:
            self._log_failure("deliver", cop)
            return user_message_for_error(cop)
        except Exception as cop:
            self._log_failure("deliver", cop)
            return "下载或发送失败了，请稍后再试。"
        finally:
            _cleanup_dir(work)
        return delivered

    async def _deliver(self, client, parsed, source_url: str, context: dict, work: Path):
        from services.plugin_ports import resolve_gateway

        port = resolve_gateway(context)
        if port is None:
            raise XDownloadError("send", "gateway unavailable")
        title = parsed.title or "已解析"
        if parsed.media_type == "image":
            return await self._deliver_images(client, parsed, source_url, context, work, port, title)
        if not parsed.files:
            raise XDownloadError("no_media", "no file", status=400)
        media = parsed.files[0]
        path = await self._save(client, media.url, work, source_url, suffix=_suffix(media.name or media.url, ".mp4"))
        ok = await port.send_file(str(path), context, file_name=path.name)
        if not ok:
            return "文件已经下载好了，但发到 QQ 失败了。"
        return ""

    async def _deliver_images(self, client, parsed, source_url, context, work, port, title: str):
        images = list(parsed.files or [])
        saved = []
        for item in images:
            saved.append(
                await self._save(
                    client,
                    item.url,
                    work,
                    source_url,
                    suffix=_suffix(item.name or item.url, ".jpg"),
                )
            )
        if len(saved) == 1:
            ok = await port.send_image(str(saved[0]), context)
            if ok:
                return ""
            return "图片已经下载好了，但发到 QQ 失败了。"
        if len(saved) > 1:
            forwarded = await self._send_image_record(
                saved,
                context,
                port,
                title,
                source_url=parsed.source_url or source_url,
                cover_url=parsed.cover,
            )
            if forwarded:
                return ""
            reason = str(getattr(self, "_last_forward_error", "") or "").strip()
            if reason:
                return f"图片已下载，但合并转发失败了：{reason}"
        if not parsed.gallery_zip:
            if not images:
                raise XDownloadError("no_media", "no images", status=400)
            return "图片发送失败，也没有图集压缩包可用。"
        path = await self._save(client, parsed.gallery_zip, work, source_url, suffix=".zip")
        ok = await port.send_file(str(path), context, file_name=path.name or "gallery.zip")
        if not ok:
            return "图集已经下载好了，但发到 QQ 失败了。"
        return ""

    async def _send_image_record(
        self,
        paths: List[Path],
        context: dict,
        port,
        title: str,
        *,
        source_url: str = "",
        cover_url: str = "",
    ) -> bool:
        meta = (context or {}).get("channel_meta") or {}
        self_id = str(meta.get("self_id") or "10000").strip() or "10000"
        name = str(meta.get("self_name") or meta.get("bot_name") or "铃")[:36]
        nodes = []
        headline = str(title or "").strip()
        if headline:
            nodes.append(
                self._forward_node(
                    name,
                    self_id,
                    [{"type": "text", "data": {"text": headline}}],
                )
            )
        nodes.extend(
            self._forward_node(
                name,
                self_id,
                [{"type": "image", "data": {"file": path.resolve().as_uri()}}],
            )
            for path in paths
        )
        if not nodes:
            return False
        try:
            result = await port.send_forward(
                nodes, context, title=headline or "聊天记录"
            )
        except TypeError:
            try:
                result = await port.send_forward(nodes, context)
            except Exception as cop:
                self._last_forward_error = cop.__class__.__name__
                return False
        except Exception as cop:
            self._last_forward_error = cop.__class__.__name__
            return False
        if isinstance(result, dict) and not result.get("ok", True):
            self._last_forward_error = str(result.get("reason") or "forward_failed")[:80]
            return False
        return bool(result)

    @staticmethod
    def _forward_node(name: str, uin: str, content: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "type": "node",
            "data": {
                "name": name,
                "uin": uin,
                "content": content,
            },
        }

    async def _save(self, client, url: str, work: Path, source_url: str, *, suffix: str) -> Path:
        path = work / f"{uuid.uuid4().hex}{suffix}"
        await client.download(url, path, source_url=source_url)
        return path

    def _allow_rate(self, context: dict) -> bool:
        limit = _bounded_int(self._settings.get("rate_limit_per_min"), 6, 1, 60)
        key = _session_key(context)
        now = time.monotonic()
        hits = [item for item in _HITS.get(key, []) if now - item < 60]
        if len(hits) >= limit:
            _HITS[key] = hits
            return False
        hits.append(now)
        _HITS[key] = hits
        return True


def classify_natural(text: str, context: Optional[dict] = None) -> str:
    """explicit | hint | none. A bare URL is always none."""
    raw = str(text or "").strip()
    if not raw or raw.startswith("/"):
        return "none"
    if not any(verb in raw for verb in HINT_VERBS):
        return "none"
    if any(verb in raw for verb in EXPLICIT_VERBS) and _resolve_target_url(raw, context or {}):
        return "explicit"
    return "hint"


def hint_text() -> str:
    return f"如果要去水印下载，请使用：{COMMAND} 链接"


def _split_command(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    for command in COMMANDS:
        if raw == command:
            return ""
        if raw.startswith(command + " "):
            return raw[len(command) :].strip()
    return None


def _usage() -> str:
    return "用法：/去水印 链接，也可用 /提取 或 /下载。\n一次只能处理一个公开平台链接。"


def _first_url(text: str) -> str:
    found = _all_urls(text)
    return found[0] if found else ""


def _all_urls(text: str) -> List[str]:
    urls = []
    seen = set()
    for match in URL_RE.findall(str(text or "")):
        url = match.rstrip("，。,.!！?？;；)")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _context_urls(context: dict) -> List[str]:
    """Links already extracted by the QQ adapter: cards, quote, or this message."""
    meta = (context or {}).get("channel_meta") or {}
    found: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        for url in _all_urls(str(value or "")):
            if url not in seen:
                seen.add(url)
                found.append(url)

    for url in meta.get("qq_card_links") or []:
        add(url)
    reply = meta.get("reply") if isinstance(meta.get("reply"), dict) else {}
    add(reply.get("text"))
    for component in meta.get("components") or []:
        if not isinstance(component, dict):
            continue
        kind = str(component.get("type") or "").strip().lower()
        if kind not in {"json", "xml", "reply", "text"}:
            continue
        add(component.get("text"))
        data = component.get("data") if isinstance(component.get("data"), dict) else {}
        add(data.get("text") or data.get("data") or data.get("content"))
    return found


def _resolve_target_url(text: str, context: dict) -> str:
    explicit = str((context or {}).get("url") or "").strip()
    if explicit:
        return explicit
    inline = _all_urls(text)
    if len(inline) == 1:
        return inline[0]
    if len(inline) > 1:
        return ""
    recovered = _context_urls(context)
    if len(recovered) == 1:
        return recovered[0]
    return ""


def _confirm_word(text: str) -> str:
    raw = str(text or "").strip().lower()
    for alias in COMMANDS:
        if raw == alias or raw.startswith(alias + " "):
            raw = raw[len(alias) :].strip()
    return raw


def _is_confirm_reply(text: str) -> bool:
    word = _confirm_word(text)
    return word in CONFIRM_YES or word in CONFIRM_NO


def _session_key(context: dict) -> str:
    meta = (context or {}).get("channel_meta") or {}
    session = str(meta.get("session_id") or "").strip()
    user = str(meta.get("user_id") or "").strip()
    return session or user or "unknown"


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _suffix(name: str, default: str) -> str:
    clean = str(name or "").split("?", 1)[0].lower()
    for ext in IMAGE_EXTENSIONS + (".mp4", ".mov", ".webm", ".zip"):
        if clean.endswith(ext):
            return ext
    return default


def _work_dir() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "outbound" / "gateway_media" / "watermark"
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cleanup_dir(path: Path) -> None:
    try:
        for item in path.glob("*"):
            try:
                item.unlink()
            except Exception:
                pass
        path.rmdir()
    except Exception:
        pass


def natural_hint_for(text: str) -> str:
    """Used by callers that only want the soft hint. Plugin itself does not auto-speak it."""
    return hint_text() if classify_natural(text) == "hint" else ""


async def _unused_async_marker():
    # Keeps asyncio import meaningful for tests that patch to_thread later.
    await asyncio.sleep(0)
