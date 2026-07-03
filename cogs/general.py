"""일반 명령어 - 도움말, 핑, 초대링크, 프리미엄 안내."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

HELP_SECTIONS = [
    (
        "⚔️ 팀짜기 (TeamVS의 심장!)",
        "`/팀짜기` 랜덤 / 턴제 드래프트 / 경매 방식으로 팀 구성\n"
        "팀장 지정 · 예산 입찰 · 음성채널 인원 불러오기 지원",
    ),
    (
        "🎮 게임 전적 & 전투력",
        "`/롤 전적` `/롤 전투력` `/롤 랭킹` — 리그 오브 레전드\n"
        "`/배그 전적` `/배그 랭킹` — 배틀그라운드\n"
        "`/오버워치 전적` `/오버워치 랭킹` — 오버워치\n"
        "`/발로란트 전적` `/발로란트 랭킹` — 발로란트\n"
        "먼저 각 게임의 `등록` 명령어로 계정을 연동하세요!",
    ),
    (
        "🪙 경제 (모든 유저 2,000코인으로 시작!)",
        "`/출석` 매일 코인 받기 · `/지갑` 잔액 확인\n"
        "`/송금` 코인 보내기 · `/코인랭킹` 부자 순위\n"
        "`/투표보상` 하트 투표하고 코인 받기 💗",
    ),
    (
        "🎁 뽑기",
        "`/뽑기` 아이템 뽑기 (10연차 할인!) · `/천장` 보장 확인\n"
        "`/인벤토리` 보유 아이템 · `/도감` 수집률 · `/판매` 아이템 판매",
    ),
    (
        "🎰 미니게임",
        "`/동전던지기` 2배 찬스 · `/슬롯` 최대 20배!",
    ),
    (
        "🛡️ 서버관리 (관리자)",
        "`/청소` `/킥` `/밴` `/밴해제` `/타임아웃` `/타임아웃해제`\n"
        "`/슬로우모드` `/공지` `/역할지급` `/역할회수`\n"
        "`/환영설정` `/환영끄기` `/서버정보` `/유저정보`",
    ),
]


class GeneralCog(commands.Cog, name="일반"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="도움말", description="봇의 모든 명령어를 확인합니다.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=f"📚 {self.bot.user.display_name} 도움말",
            description="팀을 나누고, 겨루고, 증명하라! ⚔️",
            color=0x5865F2,
        )
        for name, value in HELP_SECTIONS:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="💗 봇이 마음에 든다면 /투표보상 에서 하트를 눌러주세요!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="핑", description="봇의 응답 속도를 확인합니다.")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"🏓 퐁! 지연시간: **{self.bot.latency * 1000:.0f}ms**"
        )

    @app_commands.command(name="초대링크", description="봇을 다른 서버에 초대하는 링크를 받습니다.")
    async def invite(self, interaction: discord.Interaction) -> None:
        perms = discord.Permissions(
            kick_members=True,
            ban_members=True,
            moderate_members=True,
            manage_messages=True,
            manage_roles=True,
            manage_channels=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            view_channel=True,
        )
        url = discord.utils.oauth_url(self.bot.user.id, permissions=perms)
        embed = discord.Embed(
            title="💌 초대해주세요!",
            description=f"[여기를 눌러 봇을 서버에 초대하세요]({url})",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="봇정보", description="봇의 정보를 확인합니다.")
    async def info_bot(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title=f"🤖 {self.bot.user.display_name}", color=0x5865F2)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="서버 수", value=f"{len(self.bot.guilds):,}개", inline=True)
        embed.add_field(
            name="유저 수",
            value=f"{sum(g.member_count or 0 for g in self.bot.guilds):,}명",
            inline=True,
        )
        embed.add_field(name="지연시간", value=f"{self.bot.latency * 1000:.0f}ms", inline=True)
        embed.set_footer(text="discord.py 기반 · /도움말 로 기능을 확인하세요!")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
