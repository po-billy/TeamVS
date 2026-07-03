"""배틀그라운드 - /배그 명령어 그룹 (PUBG 공식 API).

API 키: https://developer.pubg.com (무료, 10요청/분)
전투력 = K/D + 승률 + 평균 딜량 + Top10 비율 (통산 전적 기준)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.gameapi import GameAPIError, fetch_json

KST = timezone(timedelta(hours=9))
GAME = "pubg"
BASE = "https://api.pubg.com"

SHARD_LABEL = {"steam": "스팀", "kakao": "카카오"}

# 표시할 주요 모드 (라벨, 키 목록 - fpp 포함 합산)
MODE_GROUPS = [
    ("솔로", ["solo", "solo-fpp"]),
    ("듀오", ["duo", "duo-fpp"]),
    ("스쿼드", ["squad", "squad-fpp"]),
]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def aggregate_stats(game_mode_stats: dict) -> dict:
    """모든 모드의 통산 스탯 합산."""
    total = {"kills": 0, "wins": 0, "losses": 0, "rounds": 0, "damage": 0.0, "top10s": 0}
    for stats in game_mode_stats.values():
        total["kills"] += stats.get("kills", 0)
        total["wins"] += stats.get("wins", 0)
        total["losses"] += stats.get("losses", 0)
        total["rounds"] += stats.get("roundsPlayed", 0)
        total["damage"] += stats.get("damageDealt", 0.0)
        total["top10s"] += stats.get("top10s", 0)
    return total


def compute_pubg_power(total: dict) -> tuple[int, list[str]]:
    """배그 전투력 계산."""
    rounds = max(total["rounds"], 1)
    kd = total["kills"] / max(total["losses"], 1)
    wr = total["wins"] / rounds
    avg_dmg = total["damage"] / rounds
    top10 = total["top10s"] / rounds

    kd_b = int(_clamp(kd * 250, 0, 1500))
    wr_b = int(_clamp(wr * 3000, 0, 1500))
    dmg_b = int(_clamp(avg_dmg, 0, 600))
    top_b = int(_clamp(top10 * 1000, 0, 400))
    breakdown = [
        f"🔫 K/D {kd:.2f} → **+{kd_b:,}**",
        f"🏆 승률 {wr * 100:.1f}% ({total['wins']}승/{rounds:,}판) → **+{wr_b:,}**",
        f"💥 평균 딜량 {avg_dmg:.0f} → **+{dmg_b:,}**",
        f"🔟 Top10 비율 {top10 * 100:.0f}% → **+{top_b:,}**",
    ]
    return max(kd_b + wr_b + dmg_b + top_b, 1), breakdown


class PubgCog(commands.Cog, name="배틀그라운드"):
    pubg = app_commands.Group(name="배그", description="배틀그라운드 전적조회 · 전투력 · 랭킹")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.PUBG_API_KEY}",
            "Accept": "application/vnd.api+json",
        }

    def _check_key(self) -> Optional[str]:
        if not config.PUBG_API_KEY:
            return (
                "배그 기능이 아직 준비되지 않았어요.\n"
                "(봇 관리자: https://developer.pubg.com 에서 무료 API 키를 발급받아 "
                ".env의 `PUBG_API_KEY`에 넣어주세요)"
            )
        return None

    # ------------------------------------------------------------- 명령어
    @pubg.command(name="등록", description="배틀그라운드 계정을 연동합니다. (닉네임 대소문자 정확히!)")
    @app_commands.describe(닉네임="배그 인게임 닉네임 (대소문자 구분)", 플랫폼="플레이 플랫폼")
    @app_commands.choices(
        플랫폼=[
            app_commands.Choice(name="스팀", value="steam"),
            app_commands.Choice(name="카카오", value="kakao"),
        ]
    )
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def register(
        self,
        interaction: discord.Interaction,
        닉네임: str,
        플랫폼: app_commands.Choice[str],
    ) -> None:
        if msg := self._check_key():
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.defer()
        shard = 플랫폼.value
        try:
            data = await fetch_json(
                self.bot.web,
                f"{BASE}/shards/{shard}/players?filter[playerNames]={quote(닉네임.strip())}",
                headers=self._headers(),
                not_found="플레이어를 찾을 수 없어요. 닉네임(대소문자 구분)과 플랫폼을 확인해주세요.",
                api_name="PUBG API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return
        players = data.get("data", [])
        if not players:
            await interaction.followup.send("⚠️ 플레이어를 찾을 수 없어요.")
            return
        player = players[0]
        name = player["attributes"]["name"]
        account_id = f"{shard}:{player['id']}"
        display = f"{name} ({SHARD_LABEL[shard]})"
        await self.db.link_account(interaction.user.id, GAME, account_id, display)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 배그 계정 연동 완료",
                description=f"{interaction.user.mention} ↔ **{display}**\n이제 `/배그 전적` 을 사용해보세요!",
                color=0x2ECC71,
            )
        )

    @pubg.command(name="해제", description="연동된 배그 계정을 해제합니다.")
    async def unregister(self, interaction: discord.Interaction) -> None:
        row = await self.db.get_account(interaction.user.id, GAME)
        if not row:
            await interaction.response.send_message("연동된 계정이 없습니다.", ephemeral=True)
            return
        await self.db.unlink_account(interaction.user.id, GAME)
        await interaction.response.send_message(
            f"🔓 **{row['account_name']}** 연동을 해제했습니다.", ephemeral=True
        )

    @pubg.command(name="전적", description="배그 통산 전적과 전투력을 확인합니다. (랭킹에 반영)")
    @app_commands.describe(유저="전적을 볼 서버 멤버 (계정 연동 필요)")
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def record(
        self, interaction: discord.Interaction, 유저: Optional[discord.User] = None
    ) -> None:
        if msg := self._check_key():
            await interaction.response.send_message(msg, ephemeral=True)
            return
        target = 유저 or interaction.user
        row = await self.db.get_account(target.id, GAME)
        if not row:
            who = "해당 유저는" if 유저 else "먼저"
            await interaction.response.send_message(
                f"{who} `/배그 등록` 으로 계정을 연동해야 합니다.", ephemeral=True
            )
            return
        await interaction.response.defer()
        shard, _, player_id = row["account_id"].partition(":")
        try:
            data = await fetch_json(
                self.bot.web,
                f"{BASE}/shards/{shard}/players/{player_id}/seasons/lifetime",
                headers=self._headers(),
                not_found="전적 정보를 불러올 수 없어요. 다시 등록해보세요.",
                api_name="PUBG API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return

        gms = data.get("data", {}).get("attributes", {}).get("gameModeStats", {})
        total = aggregate_stats(gms)
        if total["rounds"] == 0:
            await interaction.followup.send("아직 플레이 기록이 없어요.")
            return
        power, breakdown = compute_pubg_power(total)
        await self.db.update_power(
            target.id, GAME, power, f"K/D {total['kills'] / max(total['losses'], 1):.2f}",
            datetime.now(KST).isoformat(timespec="seconds"),
        )

        embed = discord.Embed(
            title=f"🍳 {row['account_name']} 통산 전적",
            description=f"# 🔥 전투력 {power:,}\n\n" + "\n".join(breakdown),
            color=0xF5A623,
        )
        for label, keys in MODE_GROUPS:
            merged = {"kills": 0, "wins": 0, "losses": 0, "rounds": 0, "damage": 0.0, "top10s": 0}
            for k in keys:
                s = gms.get(k, {})
                merged["kills"] += s.get("kills", 0)
                merged["wins"] += s.get("wins", 0)
                merged["losses"] += s.get("losses", 0)
                merged["rounds"] += s.get("roundsPlayed", 0)
            if merged["rounds"] == 0:
                continue
            kd = merged["kills"] / max(merged["losses"], 1)
            embed.add_field(
                name=f"🎯 {label}",
                value=f"{merged['rounds']:,}판 · {merged['wins']}치킨 🍗\nK/D **{kd:.2f}**",
                inline=True,
            )
        embed.set_footer(text="통산(라이프타임) 기준 · /배그 랭킹 에 반영됨")
        await interaction.followup.send(embed=embed)

    @pubg.command(name="랭킹", description="이 서버 멤버들의 배그 전투력 랭킹을 확인합니다.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def ranking(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        rows = await self.db.all_powers(GAME)
        entries = []
        for row in rows:
            member = interaction.guild.get_member(row["user_id"])
            if member:
                entries.append((member, row))
            if len(entries) >= 15:
                break
        if not entries:
            await interaction.followup.send(
                "아직 랭킹 데이터가 없습니다. `/배그 등록` 후 `/배그 전적` 으로 측정해보세요!"
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{m.display_name}** — 🔥 {r['power']:,}\n"
            f"　{r['account_name']} · {r['power_detail'] or '?'}"
            for i, (m, r) in enumerate(entries)
        ]
        embed = discord.Embed(
            title=f"🍗 {interaction.guild.name} 배그 전투력 랭킹",
            description="\n".join(lines),
            color=0xF5A623,
        )
        embed.set_footer(text="갱신하려면 /배그 전적 을 다시 사용하세요!")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PubgCog(bot))
