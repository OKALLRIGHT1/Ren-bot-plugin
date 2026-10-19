from datetime import date, datetime
from typing import Any, Dict, List, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from .base import BaseAPI

logger = get_logger()


class HolidayAPI(BaseAPI):
    def __init__(self, token: str, session: Optional["aiohttp.ClientSession"] = None, year: Optional[int] = None):
        super().__init__(session)
        self.token = token
        self.url = "https://v3.alapi.cn/api/holiday"
        self.headers = {"Content-Type": "application/json"}
        self.year = year or datetime.now().year

    async def get_holidays_async(self) -> Optional[Dict]:
        try:
            session = await self._get_session()
            params = {"token": self.token}
            async with session.get(self.url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as exc:
            logger.warning(f"请求节假日 API 失败: {exc}")
            return None
        except Exception as exc:
            logger.error(f"获取节假日数据失败: {exc}", exc_info=True)
            return None

    def parse_holidays(self, api_data: Optional[Dict], max_count: int = 3) -> List[Dict]:
        if not api_data:
            return []

        try:
            holidays_data = api_data.get("data", [])
            if not isinstance(holidays_data, list) or not holidays_data:
                return []

            today = date.today()
            processed: List[Dict[str, Any]] = []
            seen = set()

            for holiday in holidays_data:
                if not isinstance(holiday, dict):
                    continue
                if holiday.get("is_off_day") != 1:
                    continue
                date_str = holiday.get("date")
                if not date_str:
                    continue
                try:
                    holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if holiday_date < today:
                    continue
                days_left = (holiday_date - today).days
                name = holiday.get("name", "未知")

                if name in seen:
                    for i, existing in enumerate(processed):
                        if existing["name"] == name and days_left < existing["days_left"]:
                            processed[i] = {"name": name, "days_left": days_left, "date": date_str}
                            break
                else:
                    seen.add(name)
                    processed.append({"name": name, "days_left": days_left, "date": date_str})

            processed.sort(key=lambda x: x["days_left"])
            result = processed[:max_count]
            if not result:
                return []
            return [{"name": item["name"], "days_left": item["days_left"]} for item in result]
        except Exception as exc:
            logger.error(f"解析节假日数据出错: {exc}", exc_info=True)
            return []

    async def get_moyu_list_async(self, max_count: int = 3) -> List[Dict]:
        api_data = await self.get_holidays_async()
        return self.parse_holidays(api_data, max_count)