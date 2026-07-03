"""한국 디스코드 리스트(koreanbots.dev) API v2 연동.

- 서버 수 업데이트: POST /v2/bots/{bot.id}/stats  (3분에 3회 제한)
- 투표 확인:       GET  /v2/bots/{bot.id}/vote?userID=...
문서: https://koreanbots.dev/developers/docs
"""
from __future__ import annotations

from typing import Optional

import aiohttp

BASE = "https://koreanbots.dev/api/v2"


class KoreanBotsError(Exception):
    pass


class KoreanBotsClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def start(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def post_stats(self, bot_id: int, servers: int) -> None:
        """봇의 서버 수를 koreanbots에 업데이트합니다."""
        if not self.enabled:
            return
        await self.start()
        headers = {"Authorization": self.token, "Content-Type": "application/json"}
        async with self.session.post(
            f"{BASE}/bots/{bot_id}/stats",
            headers=headers,
            json={"servers": servers},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise KoreanBotsError(f"서버 수 업데이트 실패 ({resp.status}): {text[:200]}")

    async def check_vote(self, bot_id: int, user_id: int) -> dict:
        """유저의 12시간 내 투표 여부를 확인합니다.

        반환: {"voted": bool, "lastVote": timestamp(ms)}
        """
        if not self.enabled:
            raise KoreanBotsError("KOREANBOTS_TOKEN이 설정되지 않았습니다.")
        await self.start()
        headers = {"Authorization": self.token, "Content-Type": "application/json"}
        async with self.session.get(
            f"{BASE}/bots/{bot_id}/vote",
            headers=headers,
            params={"userID": str(user_id)},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise KoreanBotsError(f"투표 확인 실패 ({resp.status}): {text[:200]}")
            data = await resp.json()
            return data.get("data", {})
