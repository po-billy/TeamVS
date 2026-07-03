"""서버관리 - 청소, 킥, 밴, 타임아웃, 슬로우모드, 공지, 역할, 환영 메시지."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


def _mod_check(interaction: discord.Interaction, target: discord.Member) -> Optional[str]:
    """제재 가능 여부 검사. 불가 사유 문자열 또는 None 반환."""
    guild = interaction.guild
    if target.id == interaction.user.id:
        return "자기 자신에게는 사용할 수 없어요."
    if target.id == guild.me.id:
        return "봇 자신에게는 사용할 수 없어요."
    if target.id == guild.owner_id:
        return "서버 소유자에게는 사용할 수 없어요."
    if (
        interaction.user.id != guild.owner_id
        and target.top_role >= interaction.user.top_role
    ):
        return "대상의 역할이 당신보다 높거나 같아요."
    if target.top_role >= guild.me.top_role:
        return "봇의 역할이 대상보다 낮아서 처리할 수 없어요. (봇 역할을 위로 올려주세요)"
    return None


class AdminCog(commands.Cog, name="서버관리"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------- 메시지 관리
    @app_commands.command(name="청소", description="채널의 메시지를 삭제합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    @app_commands.describe(개수="삭제할 메시지 수 (1~100)", 유저="이 유저의 메시지만 삭제")
    async def purge(
        self,
        interaction: discord.Interaction,
        개수: app_commands.Range[int, 1, 100],
        유저: Optional[discord.User] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author.id == 유저.id) if 유저 else (lambda m: True)
        deleted = await interaction.channel.purge(limit=개수, check=check)
        target = f" ({유저.display_name}님의 메시지)" if 유저 else ""
        await interaction.followup.send(f"🧹 메시지 {len(deleted)}개를 삭제했어요{target}.")

    @app_commands.command(name="슬로우모드", description="채널의 슬로우모드를 설정합니다. (0 = 해제)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    @app_commands.describe(초="메시지 전송 간격 (0~21600초)")
    async def slowmode(
        self, interaction: discord.Interaction, 초: app_commands.Range[int, 0, 21600]
    ) -> None:
        await interaction.channel.edit(slowmode_delay=초)
        if 초 == 0:
            await interaction.response.send_message("🐇 슬로우모드를 해제했어요.")
        else:
            await interaction.response.send_message(f"🐢 슬로우모드를 **{초}초**로 설정했어요.")

    # ------------------------------------------------------------- 멤버 제재
    @app_commands.command(name="킥", description="멤버를 서버에서 추방합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.describe(유저="추방할 멤버", 사유="추방 사유")
    async def kick(
        self,
        interaction: discord.Interaction,
        유저: discord.Member,
        사유: Optional[str] = None,
    ) -> None:
        if reason := _mod_check(interaction, 유저):
            await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
            return
        await 유저.kick(reason=f"{interaction.user} - {사유 or '사유 없음'}")
        await interaction.response.send_message(
            f"👢 **{유저.display_name}** 님을 추방했어요. (사유: {사유 or '없음'})"
        )

    @app_commands.command(name="밴", description="멤버를 서버에서 차단합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(유저="차단할 멤버", 사유="차단 사유", 메시지삭제="최근 며칠치 메시지를 삭제할까요?")
    async def ban(
        self,
        interaction: discord.Interaction,
        유저: discord.Member,
        사유: Optional[str] = None,
        메시지삭제: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        if reason := _mod_check(interaction, 유저):
            await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
            return
        await 유저.ban(
            reason=f"{interaction.user} - {사유 or '사유 없음'}",
            delete_message_days=메시지삭제,
        )
        await interaction.response.send_message(
            f"🔨 **{유저.display_name}** 님을 차단했어요. (사유: {사유 or '없음'})"
        )

    @app_commands.command(name="밴해제", description="차단된 유저를 해제합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(유저아이디="차단 해제할 유저의 ID")
    async def unban(self, interaction: discord.Interaction, 유저아이디: str) -> None:
        if not 유저아이디.isdigit():
            await interaction.response.send_message("올바른 유저 ID를 입력해주세요.", ephemeral=True)
            return
        try:
            user = await self.bot.fetch_user(int(유저아이디))
            await interaction.guild.unban(user, reason=str(interaction.user))
        except discord.NotFound:
            await interaction.response.send_message("차단 목록에 없는 유저예요.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔓 **{user.display_name}** 님의 차단을 해제했어요.")

    @app_commands.command(name="타임아웃", description="멤버를 일정 시간 타임아웃합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(유저="타임아웃할 멤버", 분="타임아웃 시간(분, 최대 40320 = 28일)", 사유="사유")
    async def timeout(
        self,
        interaction: discord.Interaction,
        유저: discord.Member,
        분: app_commands.Range[int, 1, 40320],
        사유: Optional[str] = None,
    ) -> None:
        if reason := _mod_check(interaction, 유저):
            await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
            return
        await 유저.timeout(
            timedelta(minutes=분), reason=f"{interaction.user} - {사유 or '사유 없음'}"
        )
        await interaction.response.send_message(
            f"🔇 **{유저.display_name}** 님을 **{분}분** 타임아웃했어요. (사유: {사유 or '없음'})"
        )

    @app_commands.command(name="타임아웃해제", description="멤버의 타임아웃을 해제합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(유저="타임아웃을 해제할 멤버")
    async def untimeout(
        self, interaction: discord.Interaction, 유저: discord.Member
    ) -> None:
        await 유저.timeout(None, reason=str(interaction.user))
        await interaction.response.send_message(
            f"🔊 **{유저.display_name}** 님의 타임아웃을 해제했어요."
        )

    # ------------------------------------------------------------- 역할
    @app_commands.command(name="역할지급", description="멤버에게 역할을 지급합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def give_role(
        self, interaction: discord.Interaction, 유저: discord.Member, 역할: discord.Role
    ) -> None:
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "봇보다 높은 역할은 지급할 수 없어요.", ephemeral=True
            )
            return
        if 역할.is_default() or 역할.managed:
            await interaction.response.send_message("지급할 수 없는 역할이에요.", ephemeral=True)
            return
        await 유저.add_roles(역할, reason=str(interaction.user))
        await interaction.response.send_message(
            f"✅ {유저.mention} 님에게 {역할.mention} 역할을 지급했어요.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="역할회수", description="멤버의 역할을 회수합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def remove_role(
        self, interaction: discord.Interaction, 유저: discord.Member, 역할: discord.Role
    ) -> None:
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "봇보다 높은 역할은 회수할 수 없어요.", ephemeral=True
            )
            return
        await 유저.remove_roles(역할, reason=str(interaction.user))
        await interaction.response.send_message(
            f"➖ {유저.mention} 님의 {역할.mention} 역할을 회수했어요.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ------------------------------------------------------------- 공지/환영
    @app_commands.command(name="공지", description="깔끔한 임베드 공지를 보냅니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(제목="공지 제목", 내용="공지 내용 (\\n 입력 시 줄바꿈)", 채널="보낼 채널 (기본: 현재 채널)", 멘션="함께 보낼 멘션")
    @app_commands.choices(
        멘션=[
            app_commands.Choice(name="없음", value="none"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="@everyone", value="everyone"),
        ]
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        제목: str,
        내용: str,
        채널: Optional[discord.TextChannel] = None,
        멘션: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        channel = 채널 or interaction.channel
        embed = discord.Embed(
            title=f"📢 {제목}",
            description=내용.replace("\\n", "\n"),
            color=0xE74C3C,
        )
        embed.set_footer(
            text=f"{interaction.guild.name} · {interaction.user.display_name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        content = None
        if 멘션 and 멘션.value == "here":
            content = "@here"
        elif 멘션 and 멘션.value == "everyone":
            content = "@everyone"
        try:
            await channel.send(content=content, embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"{channel.mention} 채널에 보낼 권한이 없어요.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"📢 {channel.mention} 에 공지를 보냈어요!", ephemeral=True
        )

    @app_commands.command(name="환영설정", description="새 멤버 환영 메시지를 설정합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        채널="환영 메시지를 보낼 채널",
        메시지="환영 문구 - {유저} {서버} {멤버수} 사용 가능 (기본 문구 있음)",
    )
    async def welcome_set(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel,
        메시지: Optional[str] = None,
    ) -> None:
        await self.db.set_welcome(interaction.guild_id, 채널.id, 메시지)
        preview = (메시지 or "{유저} 님, {서버}에 오신 것을 환영합니다! 🎉").replace(
            "{유저}", interaction.user.mention
        ).replace("{서버}", interaction.guild.name).replace(
            "{멤버수}", str(interaction.guild.member_count)
        )
        await interaction.response.send_message(
            f"✅ 환영 메시지를 {채널.mention} 에 설정했어요!\n미리보기: {preview}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="환영끄기", description="환영 메시지를 비활성화합니다.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_off(self, interaction: discord.Interaction) -> None:
        await self.db.set_welcome(interaction.guild_id, None, None)
        await interaction.response.send_message("환영 메시지를 껐어요.")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            await self.db.ensure_user(member.id)  # 신규 유저 시작 코인 지급
        row = await self.db.get_guild_settings(member.guild.id)
        if not row or not row["welcome_channel_id"]:
            return
        channel = member.guild.get_channel(row["welcome_channel_id"])
        if not channel:
            return
        template = row["welcome_message"] or "{유저} 님, {서버}에 오신 것을 환영합니다! 🎉"
        text = (
            template.replace("{유저}", member.mention)
            .replace("{서버}", member.guild.name)
            .replace("{멤버수}", str(member.guild.member_count))
        )
        try:
            await channel.send(text)
        except discord.Forbidden:
            pass

    # ------------------------------------------------------------- 정보
    @app_commands.command(name="서버정보", description="이 서버의 정보를 확인합니다.")
    @app_commands.guild_only()
    async def server_info(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        embed = discord.Embed(title=f"📋 {g.name}", color=0x5865F2)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="👑 소유자", value=f"<@{g.owner_id}>", inline=True)
        embed.add_field(name="👥 멤버 수", value=f"{g.member_count:,}명", inline=True)
        embed.add_field(name="🚀 부스트", value=f"레벨 {g.premium_tier} ({g.premium_subscription_count}회)", inline=True)
        embed.add_field(name="💬 채널", value=f"텍스트 {len(g.text_channels)} · 음성 {len(g.voice_channels)}", inline=True)
        embed.add_field(name="🎭 역할", value=f"{len(g.roles)}개", inline=True)
        embed.add_field(name="📅 생성일", value=f"<t:{int(g.created_at.timestamp())}:D>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="유저정보", description="유저의 정보를 확인합니다.")
    @app_commands.guild_only()
    @app_commands.describe(유저="정보를 볼 멤버 (기본: 나)")
    async def user_info(
        self, interaction: discord.Interaction, 유저: Optional[discord.Member] = None
    ) -> None:
        m = 유저 or interaction.user
        embed = discord.Embed(title=f"👤 {m.display_name}", color=m.color)
        embed.set_thumbnail(url=m.display_avatar.url)
        embed.add_field(name="이름", value=f"{m} (`{m.id}`)", inline=False)
        embed.add_field(name="📅 계정 생성", value=f"<t:{int(m.created_at.timestamp())}:D>", inline=True)
        if m.joined_at:
            embed.add_field(name="📥 서버 가입", value=f"<t:{int(m.joined_at.timestamp())}:D>", inline=True)
        roles = [r.mention for r in reversed(m.roles) if not r.is_default()]
        embed.add_field(
            name=f"🎭 역할 ({len(roles)})",
            value=" ".join(roles[:15]) or "없음",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
