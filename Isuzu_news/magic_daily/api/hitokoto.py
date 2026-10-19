from typing import Dict, Optional

try:
    import aiohttp
except Exception:
    aiohttp = None

from core.logger import get_logger

from ..constants import EMPTY_HITOKOTO
from .base import BaseAPI

logger = get_logger()


class HitokotoAPI(BaseAPI):
    def __init__(self, token: str, session: Optional["aiohttp.ClientSession"] = None):
        super().__init__(session)
        self.token = token
        self.url = "https://v3.alapi.cn/api/hitokoto"
        self.headers = {"Content-Type": "application/json"}

    async def get_hitokoto_data_async(self) -> Optional[Dict]:
        try:
            session = await self._get_session()
            params = {"token": self.token}
            async with session.get(self.url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()

            code = data.get("code")
            success = data.get("success", False)
            if (code == 200 or success) and data.get("data"):
                return data
            logger.warning(f"今日一言接口返回异常: code={code}, success={success}")
            return None
        except Exception as exc:
            logger.error(f"获取今日一言失败: {exc}", exc_info=True)
            return None

    def parse_hitokoto_data(self, api_data: Optional[Dict]) -> Dict[str, str]:
        if not api_data or not isinstance(api_data.get("data"), dict):
            return dict(EMPTY_HITOKOTO)
        hitokoto_data = api_data["data"]
        from_value = hitokoto_data.get("from") or hitokoto_data.get("from_who") or ""
        if not from_value or (
            isinstance(from_value, str)
            and (from_value.strip() == "" or from_value.strip() == "网络")
        ):
            from_value = "佚名"
        else:
            from_value = str(from_value).strip()
        hitokoto_text = hitokoto_data.get("hitokoto", "")
        return {"hitokoto": hitokoto_text, "from": from_value}

    async def get_hitokoto_async(self) -> Dict[str, str]:
        api_data = await self.get_hitokoto_data_async()
        return self.parse_hitokoto_data(api_data)
