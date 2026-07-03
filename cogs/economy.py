"""경제 시스템 - 출석, 지갑, 송금, 코인 랭킹, koreanbots 투표 보상."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.koreanbots_api import KoreanBotsError

KST = timezone(timedelta(hours=9))
COIN = "🪙"


class EconomyCog(commands.Cog, name="경제"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(name="출석", description="매일 출석하고 코인을 받아가세요! (자정 KST 초기화)")
    async def daily(self, interaction: discord.Interaction) -> None:
        row = await self.db.ensure_user(interaction.user.id)
        today = datetime.now(KST).date()

        last = None
        if row["last_daily"]:
            try:
                last = date.fromisoformat(row["last_daily"])
            except ValueError:
                last = None

        if last == today:
            midnight = datetime.combine(
                today + timedelta(days=1), datetime.min.time(), tzinfo=KST
            )
            await interaction.response.send_message(
                f"이미 오늘 출석했어요! 다음 출석: <t:{int(midnight.timestamp())}:R>",
                ephemeral=True,
            )
            return

        streak = row["daily_streak"] + 1 if last == today - timedelta(days=1) else 1
        bonus = min(streak - 1, config.DAILY_STREAK_CAP) * config.DAILY_STREAK_BONUS
        reward = config.DAILY_BASE + bonus

        await self.db.set_daily(interaction.user.id, today.isoformat(), streak)
        balance = await self.db.add_coins(interaction.user.id, reward)

        embed = discord.Embed(
            title="📅 출석 완료!",
            description=(
                f"{COIN} **+{reward:,}** 코인 획득!"
                + (f" (연속 출석 {streak}일 보너스 +{bonus:,})" if bonus else "")
                + f"\n현재 잔액: **{balance:,}** 코인"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text="매일 출석하면 보너스가 커져요! (최대 +200)")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="지갑", description="보유 코인을 확인합니다.")
    @app_commands.describe(유저="다른 유저의 지갑을 확인할 수 있어요.")
    async def wallet(
        self, interaction: discord.Interaction, 유저: Optional[discord.User] = None
    ) -> None:
        target = 유저 or interaction.user
        coins = await self.db.get_coins(target.id)
        embed = discord.Embed(
            title=f"💰 {target.display_name}님의 지갑",
            description=f"{COIN} **{coins:,}** 코인",
            color=0xF1C40F,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="송금", description="다른 유저에게 코인을 보냅니다. (수수료 5%)")
    @app_commands.describe(유저="받는 사람", 금액="보낼 코인 (수수료 별도)")
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def transfer(
        self,
        interaction: discord.Interaction,
        유저: discord.User,
        금액: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        if 유저.id == interaction.user.id or 유저.bot:
            await interaction.response.send_message("잘못된 대상입니다.", ephemeral=True)
            return
        fee = max(1, int(금액 * config.TRANSFER_FEE))
        total = 금액 + fee
        if not await self.db.try_spend(interaction.user.id, total):
            coins = await self.db.get_coins(interaction.user.id)
            await interaction.response.send_message(
                f"잔액이 부족해요! 필요: {total:,} (수수료 {fee:,} 포함) / 보유: {coins:,}",
                ephemeral=True,
            )
            return
        await self.db.add_coins(유저.id, 금액)
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} → {유저.mention} {COIN} **{금액:,}** 코인 송금 완료! (수수료 {fee:,})"
        )

    @app_commands.command(name="코인랭킹", description="코인 부자 랭킹 TOP 10을 확인합니다.")
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: i.user.id)
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = await self.db.top_coins(10)
        if not rows:
            await interaction.response.send_message("아직 데이터가 없어요!")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            user = self.bot.get_user(row["user_id"])
            name = user.display_name if user else f"유저 {row['user_id']}"
            medal = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{medal} **{name}** — {COIN} {row['coins']:,}")
        embed = discord.Embed(
            title="💎 코인 부자 랭킹 TOP 10",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="투표보상",
        description="한국 디스코드 리스트에서 봇에게 하트를 누르고 보상을 받으세요! (12시간마다)",
    )
    @app_commands.checks.cooldown(3, 60.0, key=lambda i: i.user.id)
    async def vote_reward(self, interaction: discord.Interaction) -> None:
        kb = self.bot.koreanbots
        if not kb.enabled:
            await interaction.response.send_message(
                "아직 투표 보상 기능이 준비되지 않았어요. (봇 관리자: KOREANBOTS_TOKEN 설정 필요)",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        vote_url = f"https://koreanbots.dev/bots/{self.bot.user.id}/vote"
        try:
            data = await kb.check_vote(self.bot.user.id, interaction.user.id)
        except KoreanBotsError:
            await interaction.followup.send(
                f"투표 정보를 확인하지 못했어요. 잠시 후 다시 시도해주세요.\n{vote_url}"
            )
            return

        if not data.get("voted"):
            embed = discord.Embed(
                title="💗 아직 투표하지 않으셨네요!",
                description=(
                    f"[여기를 눌러 하트 투표하기]({vote_url})\n\n"
                    f"투표 후 다시 `/투표보상` 을 입력하면 {COIN} **{config.VOTE_REWARD:,}** 코인을 드려요!\n"
                    "투표는 12시간마다 가능합니다."
                ),
                color=0xE91E63,
            )
            await interaction.followup.send(embed=embed)
            return

        last_vote = int(data.get("lastVote", 0))
        row = await self.db.ensure_user(interaction.user.id)
        if row["last_vote_claim"] == last_vote:
            next_ts = int(last_vote / 1000) + 12 * 3600
            await interaction.followup.send(
                f"이번 투표 보상은 이미 받았어요! 다음 투표: <t:{next_ts}:R>\n{vote_url}"
            )
            return

        await self.db.set_vote_claim(interaction.user.id, last_vote)
        balance = await self.db.add_coins(interaction.user.id, config.VOTE_REWARD)
        embed = discord.Embed(
            title="💗 투표 감사합니다!",
            description=(
                f"{COIN} **+{config.VOTE_REWARD:,}** 코인 지급!\n"
                f"현재 잔액: **{balance:,}** 코인\n\n12시간 후에 또 투표할 수 있어요!"
            ),
            color=0xE91E63,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
