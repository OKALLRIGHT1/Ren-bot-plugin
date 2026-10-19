import xml.etree.ElementTree as ET
from html import unescape
from typing import List, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from .base import BaseAPI

logger = get_logger()


class ITHomeRSS(BaseAPI):
    def __init__(self, session: Optional["aiohttp.ClientSession"] = None):
        super().__init__(session)
        self.url = "https://www.ithome.com/rss/"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async def get_rss_async(self) -> Optional[ET.Element]:
        try:
            session = await self._get_session()
            max_size = 10 * 1024 * 1024
            async with session.get(self.url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                content = await response.read()
                if len(content) > max_size:
                    logger.warning(f"RSS 内容过大 ({len(content)} bytes)，已截断为 {max_size} bytes")
                    content = content[:max_size]
                return ET.fromstring(content)
        except aiohttp.ClientError as exc:
            logger.warning(f"请求 IT 之家 RSS 失败: {exc}")
            return None
        except ET.ParseError as exc:
            logger.warning(f"解析 RSS XML 失败: {exc}")
            return None
        except Exception as exc:
            logger.error(f"获取 RSS 数据失败: {exc}", exc_info=True)
            return None

    def parse_news(self, rss_root: Optional[ET.Element], max_count: int = 5) -> List[str]:
        if not rss_root:
            return []

        try:
            channel = rss_root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")
            news_list: List[str] = []
            for item in items[:max_count]:
                title_elem = item.find("title")
                if title_elem is not None and title_elem.text:
                    title = unescape(title_elem.text.strip())
                    title = " ".join(title.split())
                    if title:
                        news_list.append(title)

            if not news_list:
                return []
            return news_list
        except Exception as exc:
            logger.error(f"解析 RSS 数据出错: {exc}", exc_info=True)
            return []

    async def get_it_news_async(self, max_count: int = 5) -> List[str]:
        rss_root = await self.get_rss_async()
        return self.parse_news(rss_root, max_count)