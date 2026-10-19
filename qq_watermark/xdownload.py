"""x-download /v1 client and URL guards.

The API key is passed in by the caller and never logged. Downloads follow
redirects only after each hop passes the same public-host check.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

try:
    import aiohttp
except Exception:  # pragma: no cover - optional dependency
    aiohttp = None


DEFAULT_BASE_URL = "https://dl.tomori.de5.net/"
ALLOWED_HOST_SUFFIXES = (
    "douyin.com",
    "iesdouyin.com",
    "kuaishou.com",
    "gifshow.com",
    "tiktok.com",
    "tiktokv.com",
    "youtube.com",
    "youtu.be",
    "bilibili.com",
    "b23.tv",
    "x.com",
    "twitter.com",
    "t.co",
    "instagram.com",
    "xiaohongshu.com",
    "xhslink.com",
    "xhslink.cn",
    "xhscdn.com",
)
BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
# Clash / Surge fake-ip pool. Allowed platform hostnames often resolve here
# on a proxied Windows box; treating them as RFC1918 would reject Xiaohongshu.
FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
MAX_REDIRECTS = 4


class XDownloadError(Exception):
    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = str(code or "error")
        self.status = int(status or 0)


@dataclass
class MediaFile:
    url: str
    name: str = ""
    kind: str = "file"
    size: int = 0


@dataclass
class ParseResult:
    media_type: str
    title: str = ""
    files: List[MediaFile] = field(default_factory=list)
    gallery_zip: str = ""
    raw_type: str = ""
    cover: str = ""
    source_url: str = ""


def normalize_base_url(value: str) -> str:
    text = str(value or "").strip() or DEFAULT_BASE_URL
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise XDownloadError("bad_base_url", "解析服务地址无效")
    path = parsed.path or ""
    if path.rstrip("/").endswith("/v1"):
        path = path.rstrip("/")[: -len("/v1")]
    root = f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    return root + "/"


def _host_allowed(host: str) -> bool:
    name = str(host or "").strip().lower().rstrip(".")
    if not name or name in BLOCKED_HOSTS or name.endswith(".local"):
        return False
    return any(name == suffix or name.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def _is_fake_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in FAKE_IP_NETWORKS)


def _unsafe_ip(value: str, *, allow_fake_ip: bool = False) -> bool:
    try:
        ip = ipaddress.ip_address(str(value or "").strip("[]"))
    except ValueError:
        return False
    if allow_fake_ip and _is_fake_ip(ip):
        return False
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def validate_source_url(url: str) -> str:
    """Accept one public http(s) URL on a supported platform."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise XDownloadError("bad_url", "只接受 http 或 https 链接")
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        raise XDownloadError("bad_url", "链接缺少域名")
    if not _host_allowed(host) or _unsafe_ip(host):
        raise XDownloadError("blocked_host", "这个链接不在支持的平台范围内")
    try:
        infos = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise XDownloadError("dns_failed", "链接域名无法解析") from exc
    for info in infos:
        addr = str((info[4] or [""])[0])
        if _unsafe_ip(addr, allow_fake_ip=True):
            raise XDownloadError("blocked_host", "这个链接不在支持的平台范围内")
    return text


def validate_download_url(url: str, *, base_url: str, source_url: str = "") -> str:
    """Downloads may only come from the parser host or the source platform."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise XDownloadError("bad_download_url", "解析结果里的下载地址无效")
    host = str(parsed.hostname).strip().lower()
    if _unsafe_ip(host) or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise XDownloadError("blocked_download", "下载地址被拒绝")
    allowed = {urlparse(normalize_base_url(base_url)).hostname}
    if source_url:
        source_host = urlparse(source_url).hostname
        if source_host:
            allowed.add(str(source_host).lower())
    host_ok = host in {str(item or "").lower() for item in allowed} or _host_allowed(host)
    if not host_ok:
        raise XDownloadError("blocked_download", "下载地址不在允许的域名内")
    try:
        infos = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise XDownloadError("dns_failed", "下载地址无法解析") from exc
    for info in infos:
        if _unsafe_ip(str((info[4] or [""])[0]), allow_fake_ip=True):
            raise XDownloadError("blocked_download", "下载地址被拒绝")
    return text


def user_message_for_error(exc: XDownloadError) -> str:
    code = str(exc.code or "")
    status = int(exc.status or 0)
    if code == "missing_key" or status == 401:
        return "解析服务鉴权失败，请联系管理员检查密钥。"
    if status == 400 or code in {"no_media", "bad_url", "missing_url"}:
        return "没有识别到可下载的媒体，请检查链接后重试。"
    if status == 502 or code == "upstream":
        return "平台解析失败，可能需要登录态，或平台暂时不可用。"
    if code == "timeout":
        return "解析服务超时了，请稍后再试。"
    if code == "network":
        return "连不上解析服务，请稍后再试。"
    if code in {"blocked_host", "blocked_download"}:
        return "这个链接不在支持范围内，已拒绝处理。"
    if code == "too_large":
        return "文件太大，已停止下载。"
    if code == "too_many":
        return "一次只能处理一个链接。"
    return "解析或发送失败了，请稍后再试。"


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def interpret_parse_payload(payload: Any) -> ParseResult:
    body = _as_dict(payload)
    data = _as_dict(body.get("data")) or body
    media_type = str(data.get("type") or body.get("type") or "").strip().lower()
    title = str(data.get("title") or data.get("desc") or "").strip()
    cover = str(
        data.get("cover")
        or data.get("cover_url")
        or data.get("image")
        or data.get("thumbnail")
        or ""
    ).strip()
    source_url = str(data.get("webpage_url") or data.get("source_url") or data.get("page_url") or "").strip()
    links = _as_dict(data.get("links"))
    files: List[MediaFile] = []
    for item in links.get("files") or []:
        row = _as_dict(item)
        download = str(row.get("download") or row.get("url") or "").strip()
        if not download:
            continue
        files.append(
            MediaFile(
                url=download,
                name=str(row.get("name") or row.get("filename") or "").strip(),
                kind=str(row.get("type") or row.get("kind") or "file").strip().lower(),
                size=_safe_int(row.get("size")),
            )
        )
    gallery = str(links.get("gallery_zip") or data.get("gallery_zip") or "").strip()
    if media_type == "video" and not files:
        fallback = str(data.get("url") or "").strip()
        if not fallback:
            formats = data.get("formats")
            if isinstance(formats, list):
                for item in formats:
                    row = _as_dict(item)
                    fallback = str(row.get("url") or row.get("download") or "").strip()
                    if fallback:
                        break
        if fallback:
            files.append(MediaFile(url=fallback, kind="video"))
    if media_type == "image" and not files:
        images = data.get("images") or data.get("image_urls") or []
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.strip():
                    files.append(MediaFile(url=item.strip(), kind="image"))
                else:
                    row = _as_dict(item)
                    url = str(row.get("url") or row.get("download") or "").strip()
                    if url:
                        files.append(MediaFile(url=url, kind="image", name=str(row.get("name") or "")))
    if not media_type:
        media_type = "image" if gallery or _looks_like_images(files) else "video"
    if not files and not gallery:
        raise XDownloadError("no_media", "没有可下载媒体", status=400)
    if not cover:
        for item in files:
            if item.kind == "image" or str(item.name or item.url).lower().split("?", 1)[0].endswith(IMAGE_EXTENSIONS):
                cover = item.url
                break
    return ParseResult(
        media_type="image" if media_type == "image" else "video",
        title=title[:120],
        files=files,
        gallery_zip=gallery,
        raw_type=media_type,
        cover=cover,
        source_url=source_url,
    )


def _looks_like_images(files: Sequence[MediaFile]) -> bool:
    if not files:
        return False
    return all(
        item.kind == "image" or str(item.name or item.url).lower().split("?", 1)[0].endswith(IMAGE_EXTENSIONS)
        for item in files
    )


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def map_http_error(status: int, text: str = "") -> XDownloadError:
    if status == 401:
        return XDownloadError("auth", "unauthorized", status=401)
    if status == 400:
        return XDownloadError("no_media", "bad request", status=400)
    if status >= 500:
        return XDownloadError("upstream", "upstream failed", status=status)
    return XDownloadError("http", "request failed", status=status)


class XDownloadClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_sec: float = 180,
        max_bytes: int = 80 * 1024 * 1024,
    ):
        self.base_url = normalize_base_url(base_url)
        self.api_key = str(api_key or "").strip()
        self.timeout_sec = max(5.0, float(timeout_sec or 180))
        self.max_bytes = max(1, int(max_bytes or 1))

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise XDownloadError("missing_key", "missing api key")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "live2d-llm-qq-watermark",
        }

    def _endpoint(self, path: str) -> str:
        return urljoin(self.base_url, "v1/" + str(path or "").lstrip("/"))

    def _session(self, timeout) -> "aiohttp.ClientSession":
        # Cloudflare on this host has a broken IPv4 cert in some CN networks.
        # Happy Eyeballs lets a working IPv6/IPv4 win instead of dying on the first A record.
        connector = aiohttp.TCPConnector(happy_eyeballs_delay=0.15, ttl_dns_cache=30)
        return aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def parse(self, url: str) -> ParseResult:
        source = validate_source_url(url)
        if aiohttp is None:
            raise XDownloadError("network", "aiohttp 未安装")
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec, sock_connect=15)
        try:
            async with self._session(timeout) as session:
                async with session.post(
                    self._endpoint("parse"),
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"url": source},
                ) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise map_http_error(resp.status, text)
        except XDownloadError:
            raise
        except (TimeoutError, aiohttp.ServerTimeoutError) as exc:
            raise XDownloadError("timeout", "timeout") from exc
        except aiohttp.ClientError as exc:
            raise XDownloadError("network", "network") from exc
        try:
            import json

            payload = json.loads(text)
        except Exception as exc:
            raise XDownloadError("upstream", "invalid json") from exc
        return interpret_parse_payload(payload)

    async def download(
        self,
        url: str,
        dest,
        *,
        source_url: str = "",
    ) -> int:
        if aiohttp is None:
            raise XDownloadError("network", "aiohttp 未安装")
        current = validate_download_url(url, base_url=self.base_url, source_url=source_url)
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec, sock_connect=15)
        try:
            async with self._session(timeout) as session:
                for _ in range(MAX_REDIRECTS + 1):
                    async with session.get(
                        current,
                        headers=self._headers(),
                        allow_redirects=False,
                    ) as resp:
                        if resp.status in {301, 302, 303, 307, 308}:
                            location = resp.headers.get("Location", "")
                            if not location:
                                raise XDownloadError("upstream", "redirect missing")
                            current = validate_download_url(
                                urljoin(current, location),
                                base_url=self.base_url,
                                source_url=source_url,
                            )
                            continue
                        if resp.status >= 400:
                            raise map_http_error(resp.status)
                        written = 0
                        with open(dest, "wb") as handle:
                            async for chunk in resp.content.iter_chunked(65536):
                                if not chunk:
                                    continue
                                written += len(chunk)
                                if written > self.max_bytes:
                                    raise XDownloadError("too_large", "too large")
                                handle.write(chunk)
                        return written
        except XDownloadError:
            try:
                dest.unlink(missing_ok=True)
            except TypeError:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            raise
        except (TimeoutError, aiohttp.ServerTimeoutError) as exc:
            raise XDownloadError("timeout", "timeout") from exc
        except aiohttp.ClientError as exc:
            raise XDownloadError("network", "network") from exc
        raise XDownloadError("upstream", "too many redirects")
