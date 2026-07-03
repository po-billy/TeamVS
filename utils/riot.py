"""Riot API 클라이언트.

2025년 6월부로 소환사명/summonerId 기반 엔드포인트가 제거되어
Riot ID(닉네임#태그) -> PUUID 기반으로만 조회합니다.

- ACCOUNT-V1  (asia)  : Riot ID -> PUUID
- SUMMONER-V4 (kr)    : 레벨, 프로필 아이콘
- LEAGUE-V4   (kr)    : 랭크 정보 (by-puuid)
- MATCH-V5    (asia)  : 매치 기록
- CHAMPION-MASTERY-V4 (kr) : 챔피언 숙련도
- Data Dragon         : 챔피언 한글 이름, 이미지 (키 불필요)
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional
from urllib.parse import quote

import aiohttp

PLATFORM = "https://kr.api.riotgames.com"
REGIONAL = "https://asia.api.riotgames.com"
DDRAGON = "https://ddragon.leagueoflegends.com"

QUEUE_NAMES = {
    420: "솔로랭크",
    440: "자유랭크",
    430: "일반",
    400: "일반",
    450: "칼바람",
    490: "빠른대전",
    700: "격전",
    1700: "아레나",
}


class RiotAPIError(Exception):
    """Riot API 오류. 유저에게 보여줄 한국어 메시지를 담습니다."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


class RiotClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self._ddragon_version: Optional[str] = None
        # 챔피언 숫자 key -> (영문 id, 한글 이름)
        self._champions: dict[int, tuple[str, str]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def start(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    # ------------------------------------------------------------- 내부 요청
    async def _get(self, url: str, retry: bool = True) -> Any:
        if not self.enabled:
            raise RiotAPIError(0, "Riot API 키가 설정되지 않았습니다. (.env의 RIOT_API_KEY)")
        await self.start()
        headers = {"X-Riot-Token": self.api_key}
        async with self.session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            if resp.status == 429 and retry:
                retry_after = int(resp.headers.get("Retry-After", "2"))
                if retry_after <= 5:
                    await asyncio.sleep(retry_after)
                    return await self._get(url, retry=False)
                raise RiotAPIError(429, "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
            if resp.status == 404:
                raise RiotAPIError(404, "검색 결과를 찾을 수 없습니다. 닉네임#태그를 확인해주세요.")
            if resp.status in (401, 403):
                raise RiotAPIError(
                    resp.status,
                    "Riot API 키가 만료되었거나 잘못되었습니다. (개발용 키는 24시간마다 갱신 필요)",
                )
            raise RiotAPIError(resp.status, f"Riot API 오류가 발생했습니다. (코드 {resp.status})")

    # ------------------------------------------------------------- 엔드포인트
    async def account_by_riot_id(self, game_name: str, tag_line: str) -> dict:
        url = f"{REGIONAL}/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
        return await self._get(url)

    async def summoner_by_puuid(self, puuid: str) -> dict:
        return await self._get(f"{PLATFORM}/lol/summoner/v4/summoners/by-puuid/{puuid}")

    async def league_by_puuid(self, puuid: str) -> list[dict]:
        return await self._get(f"{PLATFORM}/lol/league/v4/entries/by-puuid/{puuid}")

    async def mastery_top(self, puuid: str, count: int = 3) -> list[dict]:
        url = f"{PLATFORM}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}"
        return await self._get(url)

    async def match_ids(self, puuid: str, count: int = 10) -> list[str]:
        url = f"{REGIONAL}/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}"
        return await self._get(url)

    async def match(self, match_id: str) -> dict:
        return await self._get(f"{REGIONAL}/lol/match/v5/matches/{match_id}")

    async def recent_matches(self, puuid: str, count: int = 10) -> list[dict]:
        """최근 매치 상세를 병렬로 가져옵니다."""
        ids = await self.match_ids(puuid, count)
        if not ids:
            return []
        results = await asyncio.gather(
            *(self.match(mid) for mid in ids), return_exceptions=True
        )
        return [m for m in results if isinstance(m, dict)]

    # ------------------------------------------------------------- Data Dragon
    async def _load_ddragon(self) -> None:
        await self.start()
        async with self.session.get(f"{DDRAGON}/api/versions.json") as resp:
            versions = await resp.json()
        self._ddragon_version = versions[0]
        url = f"{DDRAGON}/cdn/{self._ddragon_version}/data/ko_KR/champion.json"
        async with self.session.get(url) as resp:
            data = await resp.json()
        self._champions = {
            int(info["key"]): (cid, info["name"])
            for cid, info in data["data"].items()
        }

    async def champion_name(self, champion_id: int) -> str:
        """챔피언 숫자 ID -> 한글 이름."""
        if not self._champions:
            try:
                await self._load_ddragon()
            except Exception:
                return f"챔피언#{champion_id}"
        info = self._champions.get(champion_id)
        return info[1] if info else f"챔피언#{champion_id}"

    async def ddragon_version(self) -> str:
        if not self._ddragon_version:
            try:
                await self._load_ddragon()
            except Exception:
                return "15.1.1"
        return self._ddragon_version

    async def profile_icon_url(self, icon_id: int) -> str:
        ver = await self.ddragon_version()
        return f"{DDRAGON}/cdn/{ver}/img/profileicon/{icon_id}.png"


def parse_riot_id(raw: str) -> tuple[str, str]:
    """'닉네임#태그' 문자열을 (닉네임, 태그)로 분리합니다."""
    raw = raw.strip()
    if "#" not in raw:
        raise ValueError("닉네임#태그 형식으로 입력해주세요. 예) Hide on bush#KR1")
    name, _, tag = raw.rpartition("#")
    name, tag = name.strip(), tag.strip()
    if not name or not tag:
        raise ValueError("닉네임#태그 형식으로 입력해주세요. 예) Hide on bush#KR1")
    return name, tag
