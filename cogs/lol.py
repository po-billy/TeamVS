"""리그 오브 레전드 - /롤 명령어 그룹 (등록, 전적, 전투력, 랭킹).

TeamVS는 게임별 명령어 그룹 구조를 사용합니다:
  /롤 전적, /롤 전투력 ... → 이후 /발로란트, /배그 등 다른 게임 그룹 추가 가능
새 게임을 추가하려면 cogs/_game_template.py 를 참고하세요.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.power import compute_power, format_rank
from utils.riot import QUEUE_NAMES, RiotAPIError, parse_riot_id

KST = timezone(timedelta(hours=9))
GAME = "lol"  # game_accounts 테이블의 게임 식별자

TIER_COLORS = {
    "IRON": 0x51484A,
    "BRONZE": 0x8C513A,
    "SILVER": 0x80989D,
    "GOLD": 0xCD8837,
    "PLATINUM": 0x4E9996,
    "EMERALD": 0x149C3A,
    "DIAMOND": 0x576BCE,
    "MASTER": 0x9D48E0,
    "GRANDMASTER": 0xCD4545,
    "CHALLENGER": 0xF4C874,
}


class LoLCog(commands.Cog, name="리그오브레전드"):
    lol = app_commands.Group(name="롤", description="리그 오브 레전드 전적조회 · 전투력 · 랭킹")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def riot(self):
        return self.bot.riot

    # ------------------------------------------------------------- 내부 헬퍼
    async def _resolve_puuid(
        self,
        interaction: discord.Interaction,
        유저: Optional[discord.User],
        닉네임태그: Optional[str],
    ) -> tuple[str, str]:
        """(puuid, 표시이름) 결정. 우선순위: 닉네임태그 > 유저 > 본인."""
        if 닉네임태그:
            name, tag = parse_riot_id(닉네임태그)
            account = await self.riot.account_by_riot_id(name, tag)
            display = f"{account.get('gameName', name)}#{account.get('tagLine', tag)}"
            return account["puuid"], display

        target = 유저 or interaction.user
        row = await self.db.get_account(target.id, GAME)
        if not row:
            who = "해당 유저는" if 유저 else "먼저"
            raise RiotAPIError(
                0,
                f"{who} `/롤 등록` 으로 라이엇 계정을 연동해야 합니다. "
                "또는 `닉네임태그` 옵션에 직접 입력해주세요. 예) Hide on bush#KR1",
            )
        return row["account_id"], row["account_name"]

    async def _fetch_profile(self, puuid: str):
        summoner, leagues = await asyncio.gather(
            self.riot.summoner_by_puuid(puuid),
            self.riot.league_by_puuid(puuid),
        )
        solo = next((e for e in leagues if e.get("queueType") == "RANKED_SOLO_5x5"), None)
        flex = next((e for e in leagues if e.get("queueType") == "RANKED_FLEX_SR"), None)
        return summoner, solo, flex

    async def _recent_stats(self, puuid: str, count: int = 10):
        """최근 매치 통계와 매치별 요약 라인을 반환합니다."""
        matches = await self.riot.recent_matches(puuid, count)
        stats = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0}
        lines: list[str] = []
        matches.sort(
            key=lambda m: m.get("info", {}).get("gameEndTimestamp", 0), reverse=True
        )
        for m in matches:
            info = m.get("info", {})
            me = next(
                (p for p in info.get("participants", []) if p.get("puuid") == puuid),
                None,
            )
            if not me:
                continue
            win = bool(me.get("win"))
            stats["games"] += 1
            stats["wins"] += 1 if win else 0
            stats["kills"] += me.get("kills", 0)
            stats["deaths"] += me.get("deaths", 0)
            stats["assists"] += me.get("assists", 0)

            champ = await self.riot.champion_name(me.get("championId", 0))
            queue = QUEUE_NAMES.get(info.get("queueId", 0), "기타")
            kda = f"{me.get('kills', 0)}/{me.get('deaths', 0)}/{me.get('assists', 0)}"
            end_ts = info.get("gameEndTimestamp")
            when = f" <t:{int(end_ts / 1000)}:R>" if end_ts else ""
            emoji = "✅" if win else "❌"
            lines.append(f"{emoji} **{champ}** {kda} · {queue}{when}")
        return stats, lines

    # ------------------------------------------------------------- 명령어
    @lol.command(name="등록", description="라이엇 계정(닉네임#태그)을 내 디스코드에 연동합니다.")
    @app_commands.describe(닉네임태그="라이엇 ID를 입력하세요. 예) Hide on bush#KR1")
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def register(self, interaction: discord.Interaction, 닉네임태그: str) -> None:
        await interaction.response.defer()
        try:
            name, tag = parse_riot_id(닉네임태그)
            account = await self.riot.account_by_riot_id(name, tag)
        except ValueError as e:
            await interaction.followup.send(f"⚠️ {e}")
            return
        except RiotAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return
        display = f"{account.get('gameName', name)}#{account.get('tagLine', tag)}"
        await self.db.link_account(interaction.user.id, GAME, account["puuid"], display)
        embed = discord.Embed(
            title="✅ 계정 연동 완료",
            description=(
                f"{interaction.user.mention} ↔ **{display}**\n"
                "이제 `/롤 전적`, `/롤 전투력` 을 옵션 없이 사용할 수 있어요!"
            ),
            color=0x2ECC71,
        )
        await interaction.followup.send(embed=embed)

    @lol.command(name="해제", description="연동된 라이엇 계정을 해제합니다.")
    async def unregister(self, interaction: discord.Interaction) -> None:
        row = await self.db.get_account(interaction.user.id, GAME)
        if not row:
            await interaction.response.send_message("연동된 계정이 없습니다.", ephemeral=True)
            return
        await self.db.unlink_account(interaction.user.id, GAME)
        await interaction.response.send_message(
            f"🔓 **{row['account_name']}** 연동을 해제했습니다.", ephemeral=True
        )

    @lol.command(name="전적", description="리그 오브 레전드 전적을 조회합니다.")
    @app_commands.describe(
        유저="전적을 볼 서버 멤버 (계정 연동 필요)",
        닉네임태그="직접 조회할 라이엇 ID. 예) Hide on bush#KR1",
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def record(
        self,
        interaction: discord.Interaction,
        유저: Optional[discord.User] = None,
        닉네임태그: Optional[str] = None,
    ) -> None:
        await interaction.response.defer()
        try:
            puuid, display = await self._resolve_puuid(interaction, 유저, 닉네임태그)
            summoner, solo, flex = await self._fetch_profile(puuid)
            (stats, lines), masteries = await asyncio.gather(
                self._recent_stats(puuid, 10),
                self.riot.mastery_top(puuid, 3),
            )
        except ValueError as e:
            await interaction.followup.send(f"⚠️ {e}")
            return
        except RiotAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return

        tier = (solo or flex or {}).get("tier", "")
        embed = discord.Embed(
            title=f"🔍 {display}",
            color=TIER_COLORS.get(tier, 0x5865F2),
        )
        embed.set_thumbnail(
            url=await self.riot.profile_icon_url(summoner.get("profileIconId", 0))
        )
        embed.add_field(name="🏆 솔로랭크", value=format_rank(solo), inline=True)
        embed.add_field(name="🎏 자유랭크", value=format_rank(flex), inline=True)
        embed.add_field(name="⭐ 레벨", value=str(summoner.get("summonerLevel", "?")), inline=True)

        if masteries:
            mastery_lines = []
            for m in masteries:
                champ = await self.riot.champion_name(m.get("championId", 0))
                mastery_lines.append(
                    f"**{champ}** Lv.{m.get('championLevel', 0)} ({m.get('championPoints', 0):,}점)"
                )
            embed.add_field(name="💎 모스트 챔피언", value="\n".join(mastery_lines), inline=False)

        if stats["games"]:
            deaths = max(stats["deaths"], 1)
            kda = (stats["kills"] + stats["assists"]) / deaths
            wr = stats["wins"] / stats["games"] * 100
            embed.add_field(
                name=f"📊 최근 {stats['games']}게임 · {stats['wins']}승 {stats['games'] - stats['wins']}패 (승률 {wr:.0f}%, KDA {kda:.2f})",
                value="\n".join(lines[:10]) or "-",
                inline=False,
            )
        else:
            embed.add_field(name="📊 최근 전적", value="최근 게임 기록이 없습니다.", inline=False)

        embed.set_footer(text="전투력이 궁금하다면 /롤 전투력 을 사용해보세요!")
        await interaction.followup.send(embed=embed)

    @lol.command(name="전투력", description="전적을 분석해 전투력을 측정합니다. (랭킹에 반영)")
    @app_commands.describe(
        유저="전투력을 측정할 서버 멤버 (계정 연동 필요)",
        닉네임태그="직접 측정할 라이엇 ID (랭킹 미반영). 예) Hide on bush#KR1",
    )
    @app_commands.checks.cooldown(2, 60.0, key=lambda i: i.user.id)
    async def power(
        self,
        interaction: discord.Interaction,
        유저: Optional[discord.User] = None,
        닉네임태그: Optional[str] = None,
    ) -> None:
        await interaction.response.defer()
        try:
            puuid, display = await self._resolve_puuid(interaction, 유저, 닉네임태그)
            summoner, solo, flex = await self._fetch_profile(puuid)
            stats, _ = await self._recent_stats(puuid, 10)
        except ValueError as e:
            await interaction.followup.send(f"⚠️ {e}")
            return
        except RiotAPIError as e:
            await interaction.followup.send(f"⚠️ {e.message}")
            return

        power, breakdown = compute_power(
            solo, flex, summoner.get("summonerLevel", 0), stats
        )

        # 연동된 유저 조회라면 랭킹용으로 저장
        saved = ""
        if not 닉네임태그:
            target = 유저 or interaction.user
            row = await self.db.get_account(target.id, GAME)
            if row and row["account_id"] == puuid:
                await self.db.update_power(
                    target.id,
                    GAME,
                    power,
                    format_rank(solo or flex),
                    datetime.now(KST).isoformat(timespec="seconds"),
                )
                saved = "\n\n💾 서버 랭킹에 반영되었습니다. `/롤 랭킹` 으로 확인!"

        tier = (solo or flex or {}).get("tier", "")
        embed = discord.Embed(
            title=f"⚡ {display} 의 전투력",
            description=f"# 🔥 {power:,}\n\n" + "\n".join(breakdown) + saved,
            color=TIER_COLORS.get(tier, 0xE67E22),
        )
        embed.set_thumbnail(
            url=await self.riot.profile_icon_url(summoner.get("profileIconId", 0))
        )
        await interaction.followup.send(embed=embed)

    @lol.command(name="랭킹", description="이 서버 멤버들의 롤 전투력 랭킹을 확인합니다.")
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
                "아직 랭킹 데이터가 없습니다. `/롤 등록` 후 `/롤 전투력` 으로 측정해보세요!"
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (member, row) in enumerate(entries):
            medal = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(
                f"{medal} **{member.display_name}** — 🔥 {row['power']:,}\n"
                f"　{row['account_name']} · {row['power_detail'] or '?'}"
            )

        embed = discord.Embed(
            title=f"🏆 {interaction.guild.name} 롤 전투력 랭킹",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        embed.set_footer(text="전투력은 /롤 전투력 사용 시점 기준입니다. 갱신하려면 다시 측정하세요!")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoLCog(bot))
