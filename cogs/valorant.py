"""발로란트 - /발로란트 명령어 그룹 (HenrikDev API).

⚠️ Riot 공식 API의 발로란트 데이터는 별도 승인이 필요해서,
   커뮤니티 표준인 HenrikDev API를 사용합니다.
   무료 키 발급: https://api.henrikdev.xyz/dashboard (HenrikDev 디스코드 가입 필요)
전투력 = 경쟁전 ELO 기반 + 계정 레벨
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
from utils.riot import parse_riot_id

KST = timezone(timedelta(hours=9))
GAME = "valorant"
BASE = "https://api.henrikdev.xyz"

TIER_KO = {
    "Iron": "아이언",
    "Bronze": "브론즈",
    "Silver": "실버",
    "Gold": "골드",
    "Platinum": "플래티넘",
    "Diamond": "다이아몬드",
    "Ascendant": "초월자",
    "Immortal": "불멸",
    "Radiant": "레디언트",
    "Unrated": "언랭크",
    "Unranked": "언랭크",
}


def tier_ko(patched: Optional[str]) -> str:
    """'Diamond 2' -> '다이아몬드 2'"""
    if not patched:
        return "언랭크"
    parts = patched.split()
    name = TIER_KO.get(parts[0], parts[0])
    return f"{name} {parts[1]}" if len(parts) > 1 else name


def compute_val_power(
    elo: Optional[int], tier_patched: Optional[str], level: int
) -> tuple[int, list[str]]:
    """발로란트 전투력 계산. HenrikDev ELO(아이언1=0 ~ 레디언트 2500+)를 기반으로 사용."""
    breakdown: list[str] = []
    if elo:
        power = float(elo)
        breakdown.append(f"🏆 경쟁전 {tier_ko(tier_patched)} (ELO {elo:,}) → **+{elo:,}**")
    else:
        power = 500.0
        breakdown.append("🏆 경쟁전 미배치 기본 점수 → **+500**")
    lv_b = min(int(level * 0.5), 250)
    power += lv_b
    breakdown.append(f"⭐ 계정 레벨 {level} → **+{lv_b:,}**")
    return max(int(power), 1), breakdown


class ValorantCog(commands.Cog, name="발로란트"):
    val = app_commands.Group(name="발로란트", description="발로란트 전적조회 · 전투력 · 랭킹")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    def _headers(self) -> dict:
        return {"Authorization": config.HENRIK_API_KEY}

    def _check_key(self) -> Optional[str]:
        if not config.HENRIK_API_KEY:
            return (
                "발로란트 기능이 아직 준비되지 않았어요.\n"
                "(봇 관리자: https://api.henrikdev.xyz/dashboard 에서 무료 키를 발급받아 "
                ".env의 `HENRIK_API_KEY`에 넣어주세요 — HenrikDev 디스코드 가입 필요)"
            )
        return None

    # ------------------------------------------------------------- 명령어
    @val.command(name="등록", description="발로란트 계정(닉네임#태그)을 연동합니다.")
    @app_commands.describe(닉네임태그="라이엇 ID를 입력하세요. 예) 닉네임#KR1")
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def register(self, interaction: discord.Interaction, 닉네임태그: str) -> None:
        if msg := self._check_key():
            await interaction.response.send_message(msg, ephemeral=True)
            return
        try:
            name, tag = parse_riot_id(닉네임태그)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            data = await fetch_json(
                self.bot.web,
                f"{BASE}/valorant/v1/account/{quote(name)}/{quote(tag)}",
                headers=self._headers(),
                not_found="계정을 찾을 수 없어요. 닉네임#태그를 확인해주세요.",
                api_name="HenrikDev API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return
        acc = data.get("data", {})
        puuid = acc.get("puuid")
        region = acc.get("region", "ap")
        display = f"{acc.get('name', name)}#{acc.get('tag', tag)}"
        if not puuid:
            await interaction.followup.send("⚠️ 계정 정보를 불러오지 못했어요.")
            return
        await self.db.link_account(interaction.user.id, GAME, f"{region}:{puuid}", display)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 발로란트 계정 연동 완료",
                description=f"{interaction.user.mention} ↔ **{display}**\n이제 `/발로란트 전적` 을 사용해보세요!",
                color=0x2ECC71,
            )
        )

    @val.command(name="해제", description="연동된 발로란트 계정을 해제합니다.")
    async def unregister(self, interaction: discord.Interaction) -> None:
        row = await self.db.get_account(interaction.user.id, GAME)
        if not row:
            await interaction.response.send_message("연동된 계정이 없습니다.", ephemeral=True)
            return
        await self.db.unlink_account(interaction.user.id, GAME)
        await interaction.response.send_message(
            f"🔓 **{row['account_name']}** 연동을 해제했습니다.", ephemeral=True
        )

    @val.command(name="전적", description="발로란트 경쟁전 티어와 전투력을 확인합니다. (랭킹에 반영)")
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
                f"{who} `/발로란트 등록` 으로 계정을 연동해야 합니다.", ephemeral=True
            )
            return
        await interaction.response.defer()
        region, _, puuid = row["account_id"].partition(":")
        try:
            mmr = await fetch_json(
                self.bot.web,
                f"{BASE}/valorant/v2/by-puuid/mmr/{region}/{puuid}",
                headers=self._headers(),
                not_found="경쟁전 정보를 찾을 수 없어요. 최근 경쟁전 기록이 있는지 확인해주세요.",
                api_name="HenrikDev API",
            )
            account = await fetch_json(
                self.bot.web,
                f"{BASE}/valorant/v1/by-puuid/account/{puuid}",
                headers=self._headers(),
                not_found="계정 정보를 찾을 수 없어요.",
                api_name="HenrikDev API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return

        current = (mmr.get("data") or {}).get("current_data") or {}
        highest = (mmr.get("data") or {}).get("highest_rank") or {}
        acc = account.get("data") or {}
        level = acc.get("account_level", 0)

        power, breakdown = compute_val_power(
            current.get("elo"), current.get("currenttier_patched"), level
        )
        await self.db.update_power(
            target.id, GAME, power, tier_ko(current.get("currenttier_patched")),
            datetime.now(KST).isoformat(timespec="seconds"),
        )

        embed = discord.Embed(
            title=f"🔺 {row['account_name']}",
            description=f"# 🔥 전투력 {power:,}\n\n" + "\n".join(breakdown),
            color=0xFF4655,
        )
        embed.add_field(
            name="🏆 현재 티어",
            value=f"{tier_ko(current.get('currenttier_patched'))} · {current.get('ranking_in_tier', 0)}RR",
            inline=True,
        )
        if highest.get("patched_tier"):
            embed.add_field(
                name="⛰️ 최고 티어",
                value=tier_ko(highest.get("patched_tier")),
                inline=True,
            )
        embed.add_field(name="⭐ 레벨", value=str(level), inline=True)
        if acc.get("card", {}) and isinstance(acc.get("card"), dict) and acc["card"].get("small"):
            embed.set_thumbnail(url=acc["card"]["small"])
        embed.set_footer(text="HenrikDev API 기준 · /발로란트 랭킹 에 반영됨")
        await interaction.followup.send(embed=embed)

    @val.command(name="랭킹", description="이 서버 멤버들의 발로란트 전투력 랭킹을 확인합니다.")
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
                "아직 랭킹 데이터가 없습니다. `/발로란트 등록` 후 `/발로란트 전적` 으로 측정해보세요!"
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{m.display_name}** — 🔥 {r['power']:,}\n"
            f"　{r['account_name']} · {r['power_detail'] or '?'}"
            for i, (m, r) in enumerate(entries)
        ]
        embed = discord.Embed(
            title=f"🔺 {interaction.guild.name} 발로란트 전투력 랭킹",
            description="\n".join(lines),
            color=0xFF4655,
        )
        embed.set_footer(text="갱신하려면 /발로란트 전적 을 다시 사용하세요!")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ValorantCog(bot))
