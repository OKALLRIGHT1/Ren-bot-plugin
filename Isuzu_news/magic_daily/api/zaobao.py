from typing import Dict, List, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from ..constants import NUMBER_PREFIX_PATTERN
from .base import BaseAPI

logger = get_logger()


class ZaobaoAPI(BaseAPI):
    def __init__(self, token: str, session: Optional["aiohttp.ClientSession"] = None):
        super().__init__(session)
        self.token = token
        self.url = "https://v3.alapi.cn/api/zaobao"
        self.headers = {"Content-Type": "application/json"}

    async def get_zaobao_async(self) -> Optional[Dict]:
        try:
            session = await self._get_session()
            params = {"token": self.token, "format": "json"}
            async with session.get(self.url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as exc:
            logger.warning(f"请求早报 API 失败: {exc}")
            return None
        except Exception as exc:
            logger.error(f"获取早报数据失败: {exc}", exc_info=True)
            return None

    def parse_news(self, api_data: Optional[Dict], max_count: int = 5) -> List[str]:
        if not api_data:
            return []

        try:
            if isinstance(api_data.get("data"), dict):
                news_data = api_data["data"].get("news", [])
                if isinstance(news_data, list):
                    news_list: List[str] = []
                    for item in news_data:
                        if isinstance(item, str):
                            cleaned = NUMBER_PREFIX_PATTERN.sub("", item.strip())
                            if cleaned:
                                news_list.append(cleaned)
                        if len(news_list) >= max_count:
                            break
                    if news_list:
                        return news_list
            return []
        except Exception as exc:
            logger.error(f"解析早报数据出错: {exc}", exc_info=True)
            return []

    async def get_world_news_async(self, max_count: int = 5) -> List[str]:
        api_data = await self.get_zaobao_async()
        return self.parse_news(api_data, max_count)