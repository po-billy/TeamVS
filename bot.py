"""TeamVS 디스코드 봇 엔트리포인트.

실행: python bot.py
사전 준비: .env.example 을 .env 로 복사 후 토큰 입력
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.database import Database
from utils.koreanbots_api import KoreanBotsClient
from utils.riot import RiotClient

log = logging.getLogger("bot")

EXTENSIONS = [
    "cogs.general",
    "cogs.economy",
    "cogs.gacha",
    "cogs.lol",
    "cogs.pubg",
    "cogs.overwatch",
    "cogs.valorant",
    "cogs.team",
    "cogs.admin",
]

KOREANBOTS_UPDATE_INTERVAL = 1800  # 30분 (레이트리밋: 3분당 3회)


class TeamVSBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True  # 환영 메시지, 팀짜기, 랭킹에 필요 (개발자 포털에서도 활성화!)
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.db = Database(config.DB_PATH, starting_coins=config.STARTING_COINS)
        self.riot = RiotClient(config.RIOT_API_KEY)
        self.koreanbots = KoreanBotsClient(config.KOREANBOTS_TOKEN)
        self.web: aiohttp.ClientSession | None = None  # 게임 전적 API 공용 세션

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.riot.start()
        self.web = aiohttp.ClientSession()

        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("코그 로드: %s", ext)

        self.tree.on_error = self.on_app_command_error

        # 명령어는 전역으로만 등록 (요즘 디스코드는 전역 등록도 즉시 반영됨)
        await self.tree.sync()
        log.info("전역 명령어 등록 완료 (%d개)", len(self.tree.get_commands()))

        # 과거에 테스트 서버 전용으로 복사·등록된 중복 명령어 정리
        # (봇이 해당 서버에 없으면 실패할 수 있으므로 실패해도 계속 진행)
        if config.TEST_GUILD_ID:
            guild = discord.Object(id=config.TEST_GUILD_ID)
            self.tree.clear_commands(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                log.info("테스트 서버(%s)의 서버 전용 중복 명령어 정리 완료", config.TEST_GUILD_ID)
            except discord.HTTPException as e:
                log.warning("테스트 서버 중복 정리 건너뜀 (봇이 서버에 없거나 권한 없음): %s", e)

        if self.koreanbots.enabled:
            self.loop.create_task(self._koreanbots_stats_loop())

    async def on_ready(self) -> None:
        log.info("로그인: %s (ID: %s) · 서버 %d개", self.user, self.user.id, len(self.guilds))
        await self.change_presence(
            activity=discord.Game(name="/팀짜기 ⚔️ 팀 나누고 실력으로 증명!")
        )
        if not config.RIOT_API_KEY:
            log.warning("RIOT_API_KEY 미설정 - 롤 전적 기능이 비활성화 상태입니다.")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """봇이 새 서버에 초대되면 소개 메시지를 보냅니다."""
        log.info("새 서버 참가: %s (%s, 멤버 %s명)", guild.name, guild.id, guild.member_count)
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            channel = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
        if channel is None:
            return
        embed = discord.Embed(
            title="⚔️ TeamVS를 초대해주셔서 감사합니다!",
            description=(
                "**팀을 나누고, 겨루고, 증명하라!**\n\n"
                f"🪙 모든 유저는 **{config.STARTING_COINS:,}코인**을 가지고 시작해요!\n"
                "`/도움말` 로 전체 기능을 확인해보세요.\n\n"
                "⚔️ `/팀짜기` — 랜덤 / 턴제 드래프트 / 경매로 팀 구성\n"
                "🎮 `/롤 등록` `/배그 등록` `/오버워치 등록` — 전적조회 & 전투력 랭킹\n"
                "🎁 `/출석` → `/뽑기` — 코인 모아 아이템 수집\n"
                "🛡️ `/환영설정` — 새 멤버 환영 메시지 (관리자)"
            ),
            color=0x5865F2,
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _koreanbots_stats_loop(self) -> None:
        """koreanbots에 서버 수를 주기적으로 업데이트합니다."""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.koreanbots.post_stats(self.user.id, len(self.guilds))
                log.info("koreanbots 서버 수 업데이트: %d", len(self.guilds))
            except Exception as e:
                log.warning("koreanbots 업데이트 실패: %s", e)
            await asyncio.sleep(KOREANBOTS_UPDATE_INTERVAL)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ 잠시만요! **{error.retry_after:.0f}초** 후에 다시 사용할 수 있어요."
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 이 명령어를 사용할 권한이 없어요."
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            msg = f"🤖 봇에게 필요한 권한이 없어요: `{perms}`\n서버 설정에서 봇 권한을 확인해주세요."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "이 명령어는 서버에서만 사용할 수 있어요."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "🚫 이 명령어를 사용할 수 없어요."
        else:
            log.exception("명령어 오류", exc_info=error)
            msg = "⚠️ 오류가 발생했어요. 잠시 후 다시 시도해주세요."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await self.riot.close()
        await self.koreanbots.close()
        if self.web:
            await self.web.close()
        await self.db.close()
        await super().close()


def main() -> None:
    if not config.DISCORD_TOKEN:
        print("=" * 60)
        print("❌ DISCORD_TOKEN이 설정되지 않았습니다!")
        print()
        print("1. .env.example 파일을 복사해서 .env 로 이름을 바꾸세요.")
        print("2. https://discord.com/developers/applications 에서")
        print("   봇을 만들고 토큰을 .env 에 붙여넣으세요.")
        print("3. 자세한 방법은 README.md 를 확인하세요.")
        print("=" * 60)
        return
    bot = TeamVSBot()
    # root_logger=True: discord.py 로그뿐 아니라 봇 자체 로그(코그 로드 등)도 콘솔에 표시
    bot.run(config.DISCORD_TOKEN, log_level=logging.INFO, root_logger=True)


if __name__ == "__main__":
    main()
