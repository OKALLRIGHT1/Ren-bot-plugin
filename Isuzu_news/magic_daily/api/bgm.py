from datetime import datetime
from typing import Dict, List, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from .base import BaseAPI

logger = get_logger()


class BGMAPI(BaseAPI):
    def __init__(self, session: Optional["aiohttp.ClientSession"] = None):
        super().__init__(session)
        self.url = "https://api.bgm.tv/calendar"
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    async def get_calendar_async(self) -> Optional[List]:
        try:
            session = await self._get_session()
            async with session.get(self.url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as exc:
            logger.warning(f"请求 BGM API 失败: {exc}")
            return None
        except Exception as exc:
            logger.error(f"获取 BGM 数据失败: {exc}", exc_info=True)
            return None

    def parse_today_anime(
        self,
        api_data: Optional[List],
        max_count: int = 4,
        use_fallback: bool = False,
    ) -> List[Dict]:
        if not api_data or not isinstance(api_data, list):
            return []

        try:
            today_weekday = datetime.now().weekday() + 1
            anime_list: List[Dict[str, str]] = []

            for day_data in api_data:
                if not isinstance(day_data, dict):
                    continue
                weekday_info = day_data.get("weekday", {})
                if weekday_info.get("id") != today_weekday:
                    continue
                items = day_data.get("items", [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name_cn = item.get("name_cn", "")
                    name_jp = item.get("name", "")
                    title = name_cn or name_jp
                    images = item.get("images", {})
                    image_url = images.get("medium", "") or images.get("common", "")
                    if title and image_url:
                        anime_list.append({"title": title, "image": image_url})
                    if len(anime_list) >= max_count:
                        break
                break

            if not anime_list:
                return []
            return anime_list
        except Exception as exc:
            logger.error(f"解析 BGM 数据出错: {exc}", exc_info=True)
            return []

    async def get_today_anime_async(self, max_count: int = 4) -> List[Dict]:
        api_data = await self.get_calendar_async()
        return self.parse_today_anime(api_data, max_count)
