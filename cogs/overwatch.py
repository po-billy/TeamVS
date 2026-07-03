"""오버워치 - /오버워치 명령어 그룹 (OverFast API, 키 불필요).

OverFast API: https://overfast-api.tekrop.fr (블리자드 공개 프로필 기반)
⚠️ 배틀넷 프로필이 '공개'로 설정되어 있어야 조회됩니다.
전투력 = 최고 역할 경쟁전 티어 + 승률 + KDA
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from utils.gameapi import GameAPIError, fetch_json

KST = timezone(timedelta(hours=9))
GAME = "overwatch"
BASE = "https://overfast-api.tekrop.fr"

DIVISION_SCORE = {
    "bronze": 400,
    "silver": 800,
    "gold": 1200,
    "platinum": 1600,
    "diamond": 2000,
    "master": 2400,
    "grandmaster": 2800,
    "champion": 3200,
    "ultimate": 3200,
}
DIVISION_KO = {
    "bronze": "브론즈",
    "silver": "실버",
    "gold": "골드",
    "platinum": "플래티넘",
    "diamond": "다이아몬드",
    "master": "마스터",
    "grandmaster": "그랜드마스터",
    "champion": "챔피언",
    "ultimate": "챔피언",
}
ROLE_KO = {"tank": "🛡️ 탱커", "damage": "⚔️ 딜러", "support": "💉 힐러"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rank_text(role_data: Optional[dict]) -> str:
    if not role_data or not role_data.get("division"):
        return "배치 안 봄"
    div = DIVISION_KO.get(role_data["division"], role_data["division"])
    return f"{div} {role_data.get('tier', '?')}"


def role_score(role_data: Optional[dict]) -> int:
    if not role_data or not role_data.get("division"):
        return 0
    base = DIVISION_SCORE.get(role_data["division"], 0)
    tier = role_data.get("tier", 5)  # 5가 가장 낮음
    return base + (5 - tier) * 80


def compute_ow_power(
    ranks: dict[str, Optional[dict]], general: Optional[dict]
) -> tuple[int, list[str]]:
    """오버워치 전투력 계산. ranks: {tank/damage/support: division data}"""
    breakdown: list[str] = []
    scores = {role: role_score(data) for role, data in ranks.items()}
    best_role = max(scores, key=scores.get) if scores else None

    if best_role and scores[best_role] > 0:
        base = scores[best_role]
        breakdown.append(
            f"🏆 최고 역할 {ROLE_KO[best_role]} {rank_text(ranks[best_role])} → **+{base:,}**"
        )
    else:
        base = 500
        breakdown.append("🏆 경쟁전 미배치 기본 점수 → **+500**")

    power = float(base)
    if general:
        games = general.get("games_played", 0) or 0
        wr = general.get("winrate")
        kda = general.get("kda")
        if games >= 10 and wr is not None:
            wr_b = int(_clamp((wr - 50) * 10, -150, 300))
            power += wr_b
            sign = "+" if wr_b >= 0 else ""
            breakdown.append(f"📈 승률 {wr:.1f}% ({games:,}판) → **{sign}{wr_b:,}**")
        if kda:
            kda_b = int(_clamp(kda * 60, 0, 250))
            power += kda_b
            breakdown.append(f"⚔️ KDA {kda:.2f} → **+{kda_b:,}**")
    return max(int(power), 1), breakdown


class OverwatchCog(commands.Cog, name="오버워치"):
    ow = app_commands.Group(name="오버워치", description="오버워치 전적조회 · 전투력 · 랭킹")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------- 명령어
    @ow.command(name="등록", description="배틀태그를 연동합니다. (프로필 공개 필수!)")
    @app_commands.describe(배틀태그="배틀태그를 입력하세요. 예) 이름#12345")
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def register(self, interaction: discord.Interaction, 배틀태그: str) -> None:
        tag = 배틀태그.strip().replace(" ", "")
        if "#" not in tag:
            await interaction.response.send_message(
                "⚠️ 배틀태그 형식으로 입력해주세요. 예) 이름#12345", ephemeral=True
            )
            return
        await interaction.response.defer()
        player_id = tag.replace("#", "-")
        try:
            summary = await fetch_json(
                self.bot.web,
                f"{BASE}/players/{quote(player_id)}/summary",
                not_found="플레이어를 찾을 수 없어요. 배틀태그를 확인해주세요. (예: 이름#12345)",
                api_name="OverFast API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return
        await self.db.link_account(interaction.user.id, GAME, player_id, tag)
        warn = ""
        if summary.get("privacy") == "private":
            warn = "\n⚠️ 프로필이 **비공개** 상태예요. 게임 내 설정에서 공개로 바꿔야 전적이 보입니다."
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 오버워치 계정 연동 완료",
                description=f"{interaction.user.mention} ↔ **{tag}**\n이제 `/오버워치 전적` 을 사용해보세요!{warn}",
                color=0x2ECC71,
            )
        )

    @ow.command(name="해제", description="연동된 오버워치 계정을 해제합니다.")
    async def unregister(self, interaction: discord.Interaction) -> None:
        row = await self.db.get_account(interaction.user.id, GAME)
        if not row:
            await interaction.response.send_message("연동된 계정이 없습니다.", ephemeral=True)
            return
        await self.db.unlink_account(interaction.user.id, GAME)
        await interaction.response.send_message(
            f"🔓 **{row['account_name']}** 연동을 해제했습니다.", ephemeral=True
        )

    @ow.command(name="전적", description="오버워치 경쟁전 티어와 전투력을 확인합니다. (랭킹에 반영)")
    @app_commands.describe(유저="전적을 볼 서버 멤버 (계정 연동 필요)")
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def record(
        self, interaction: discord.Interaction, 유저: Optional[discord.User] = None
    ) -> None:
        target = 유저 or interaction.user
        row = await self.db.get_account(target.id, GAME)
        if not row:
            who = "해당 유저는" if 유저 else "먼저"
            await interaction.response.send_message(
                f"{who} `/오버워치 등록` 으로 계정을 연동해야 합니다.", ephemeral=True
            )
            return
        await interaction.response.defer()
        pid = quote(row["account_id"])
        try:
            summary = await fetch_json(
                self.bot.web,
                f"{BASE}/players/{pid}/summary",
                not_found="플레이어를 찾을 수 없어요. 다시 등록해보세요.",
                api_name="OverFast API",
            )
        except GameAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return

        if summary.get("privacy") == "private":
            await interaction.followup.send(
                "🔒 프로필이 비공개 상태예요. 오버워치 게임 내 [옵션 → 소셜]에서 "
                "경력 프로필을 공개로 바꾼 뒤 다시 시도해주세요."
            )
            return

        # 통계 요약 (없어도 티어만으로 진행)
        general = None
        try:
            stats = await fetch_json(
                self.bot.web,
                f"{BASE}/players/{pid}/stats/summary",
                not_found="",
                api_name="OverFast API",
            )
            general = stats.get("general") if isinstance(stats, dict) else None
        except GameAPIError:
            pass

        comp = summary.get("competitive") or {}
        platform = comp.get("pc") or comp.get("console") or {}
        ranks = {role: platform.get(role) for role in ("tank", "damage", "support")}

        power, breakdown = compute_ow_power(ranks, general)
        best = max(
            (rank_text(ranks[r]) for r in ranks if ranks.get(r) and ranks[r].get("division")),
            default="미배치",
        )
        await self.db.update_power(
            target.id, GAME, power, best,
            datetime.now(KST).isoformat(timespec="seconds"),
        )

        embed = discord.Embed(
            title=f"🧡 {row['account_name']}",
            description=f"# 🔥 전투력 {power:,}\n\n" + "\n".join(breakdown),
            color=0xF99E1A,
        )
        if summary.get("avatar"):
            embed.set_thumbnail(url=summary["avatar"])
        for role in ("tank", "damage", "support"):
            embed.add_field(name=ROLE_KO[role], value=rank_text(ranks.get(role)), inline=True)
        if summary.get("endorsement", {}) and summary["endorsement"].get("level"):
            embed.add_field(name="👍 존중 레벨", value=str(summary["endorsement"]["level"]), inline=True)
        embed.set_footer(text="OverFast API 기준 · /오버워치 랭킹 에 반영됨")
        await interaction.followup.send(embed=embed)

    @ow.command(name="랭킹", description="이 서버 멤버들의 오버워치 전투력 랭킹을 확인합니다.")
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
                "아직 랭킹 데이터가 없습니다. `/오버워치 등록` 후 `/오버워치 전적` 으로 측정해보세요!"
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{m.display_name}** — 🔥 {r['power']:,}\n"
            f"　{r['account_name']} · {r['power_detail'] or '?'}"
            for i, (m, r) in enumerate(entries)
        ]
        embed = discord.Embed(
            title=f"🧡 {interaction.guild.name} 오버워치 전투력 랭킹",
            description="\n".join(lines),
            color=0xF99E1A,
        )
        embed.set_footer(text="갱신하려면 /오버워치 전적 을 다시 사용하세요!")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OverwatchCog(bot))
