from typing import Dict, List, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from .base import BaseAPI

logger = get_logger()


class BilibiliAPI(BaseAPI):
    def __init__(self, session: Optional["aiohttp.ClientSession"] = None):
        super().__init__(session)
        self.url = "https://s.search.bilibili.com/main/hotword"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async def get_hotwords_data_async(self) -> Optional[Dict]:
        try:
            session = await self._get_session()
            async with session.get(self.url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
            if data.get("code") == 0 and data.get("list"):
                return data
            logger.warning(f"B站热搜接口返回异常: code={data.get('code')}")
            return None
        except Exception as exc:
            logger.error(f"获取 B站热点失败: {exc}", exc_info=True)
            return None

    async def get_hotwords_async(self, max_count: int = 4) -> List[str]:
        api_data = await self.get_hotwords_data_async()
        if not api_data:
            return []
        return self.parse_hotwords_data(api_data, max_count)

    def parse_hotwords_data(self, api_data: Optional[Dict], max_count: int = 4) -> List[str]:
        hotwords: List[str] = []
        if not api_data or not api_data.get("list"):
            return []

        for item in api_data["list"][:max_count]:
            title = item.get("show_name") or item.get("keyword", "")
            if title:
                hotwords.append(title)
        return hotwords[:max_count]
