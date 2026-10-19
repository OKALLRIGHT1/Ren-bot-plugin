from typing import Optional

try:
    import aiohttp
except Exception:
    aiohttp = None


class BaseAPI:
    """API 基类：统一管理 HTTP Session。"""

    def __init__(self, session: Optional["aiohttp.ClientSession"] = None):
        self._session = session
        self._own_session = False

    async def _get_session(self) -> "aiohttp.ClientSession":
        if aiohttp is None:
            raise RuntimeError("aiohttp not installed")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def _close_session(self):
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._own_session = False

    def set_session(self, session: "aiohttp.ClientSession"):
        self._session = session
        self._own_session = False