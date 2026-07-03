"""게임 전적 API 공용 헬퍼."""
from __future__ import annotations

from typing import Any, Optional

import aiohttp


class GameAPIError(Exception):
    """유저에게 보여줄 한국어 메시지를 담는 게임 API 오류."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: Optional[dict] = None,
    not_found: str = "검색 결과를 찾을 수 없습니다.",
    api_name: str = "게임 API",
) -> Any:
    async with session.get(url, headers=headers or {}) as resp:
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404:
            raise GameAPIError(not_found)
        if resp.status in (401, 403):
            raise GameAPIError(f"{api_name} 키가 잘못되었거나 만료되었습니다. (.env 확인)")
        if resp.status == 429:
            raise GameAPIError("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
        raise GameAPIError(f"{api_name} 오류가 발생했습니다. (코드 {resp.status})")
