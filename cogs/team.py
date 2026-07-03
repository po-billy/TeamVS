"""팀짜기 - 랜덤 / 턴제 드래프트(스네이크) / 경매(예산 입찰) 방식 지원.

흐름:
  /팀짜기 → 모집 로비(참가/나가기/팀장지정) → 시작 → 방식별 진행 → 최종 팀 발표
"""
from __future__ import annotations

import asyncio
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

MODE_RANDOM = "랜덤"
MODE_DRAFT = "턴제드래프트"
MODE_AUCTION = "경매"

MODE_DESC = {
    MODE_RANDOM: "참가자를 무작위로 배정합니다. (팀장 지정은 선택)",
    MODE_DRAFT: "팀장들이 번갈아가며 팀원을 선택합니다. (스네이크 순서: 1→2→3→3→2→1)",
    MODE_AUCTION: f"팀장들이 예산 {config.AUCTION_BUDGET:,}💰 으로 팀원을 입찰해 데려갑니다.",
}

BID_STEPS = [50, 100, 250]
AUCTION_TIMER = 20  # 입찰 없이 이 시간(초)이 지나면 자동 낙찰/유찰


# ================================================================= 세션/임베드
class TeamSession:
    def __init__(
        self, host: discord.Member, team_count: int, team_size: int, mode: str
    ) -> None:
        self.host = host
        self.team_count = team_count
        self.team_size = team_size
        self.mode = mode
        self.players: list[discord.Member] = [host]
        self.leaders: list[discord.Member] = []
        self.teams: list[list[discord.Member]] = [[] for _ in range(team_count)]

    @property
    def capacity(self) -> int:
        return self.team_count * self.team_size


def lobby_embed(s: TeamSession) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ 팀짜기 모집 중! ({s.mode})",
        description=MODE_DESC[s.mode],
        color=0x5865F2,
    )
    embed.add_field(
        name="⚙️ 설정",
        value=f"팀 수: **{s.team_count}팀** · 팀당 인원: **{s.team_size}명** · 정원: **{s.capacity}명**",
        inline=False,
    )
    lines = []
    for i, p in enumerate(s.players, 1):
        crown = " 👑" if p in s.leaders else ""
        lines.append(f"`{i}.` {p.display_name}{crown}")
    embed.add_field(
        name=f"🙋 참가자 ({len(s.players)}/{s.capacity})",
        value="\n".join(lines) if lines else "아직 없음",
        inline=False,
    )
    if s.leaders:
        embed.add_field(
            name="👑 팀장",
            value=" / ".join(
                f"{i + 1}팀 {l.display_name}" for i, l in enumerate(s.leaders)
            ),
            inline=False,
        )
    elif s.mode != MODE_RANDOM:
        embed.add_field(
            name="👑 팀장",
            value="⚠️ 아직 지정되지 않음 — 주최자가 [팀장 지정] 버튼으로 선택해주세요!",
            inline=False,
        )
    embed.set_footer(text=f"주최자: {s.host.display_name} · 주최자가 [시작]을 누르면 진행됩니다.")
    return embed


def teams_embed(
    s: TeamSession, title: str = "✅ 팀 구성 완료!", budgets: Optional[list[int]] = None
) -> discord.Embed:
    embed = discord.Embed(title=title, color=0x2ECC71)
    for i, team in enumerate(s.teams):
        lines = []
        for p in team:
            crown = "👑 " if s.leaders and p in s.leaders else ""
            lines.append(f"{crown}{p.display_name}")
        name = f"🚩 {i + 1}팀"
        if budgets is not None:
            name += f" (남은 예산 {budgets[i]:,}💰)"
        embed.add_field(name=name, value="\n".join(lines) or "-", inline=True)
    return embed


# ================================================================= 로비
class LeaderSelect(discord.ui.Select):
    def __init__(self, lobby: "LobbyView") -> None:
        self.lobby = lobby
        s = lobby.session
        options = [
            discord.SelectOption(label=p.display_name[:100], value=str(p.id))
            for p in s.players[:25]
        ]
        super().__init__(
            placeholder=f"팀장 {s.team_count}명을 선택하세요 (선택 순서 = 팀 번호)",
            min_values=s.team_count,
            max_values=s.team_count,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        s = self.lobby.session
        by_id = {p.id: p for p in s.players}
        picked = [by_id[int(v)] for v in self.values if int(v) in by_id]
        if len(picked) != s.team_count:
            await interaction.response.edit_message(
                content="⚠️ 선택한 유저 중 로비를 떠난 사람이 있어요. 다시 시도해주세요.", view=None
            )
            return
        s.leaders = picked
        await interaction.response.edit_message(
            content="👑 팀장 지정 완료: " + ", ".join(p.display_name for p in picked),
            view=None,
        )
        if self.lobby.message:
            try:
                await self.lobby.message.edit(embed=lobby_embed(s), view=self.lobby)
            except discord.HTTPException:
                pass


class LeaderSelectView(discord.ui.View):
    def __init__(self, lobby: "LobbyView") -> None:
        super().__init__(timeout=120)
        self.add_item(LeaderSelect(lobby))


class LobbyView(discord.ui.View):
    def __init__(self, session: TeamSession) -> None:
        super().__init__(timeout=900)
        self.session = session
        self.message: Optional[discord.Message] = None

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ 시간이 초과되어 팀짜기가 취소되었습니다.", view=self
                )
            except discord.HTTPException:
                pass

    async def _refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=lobby_embed(self.session), view=self)

    def _is_host(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.session.host.id

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, emoji="🙋")
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        s = self.session
        if any(p.id == interaction.user.id for p in s.players):
            await interaction.response.send_message("이미 참가 중이에요!", ephemeral=True)
            return
        if len(s.players) >= s.capacity:
            await interaction.response.send_message("정원이 가득 찼어요!", ephemeral=True)
            return
        s.players.append(interaction.user)
        await self._refresh(interaction)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        s = self.session
        s.players = [p for p in s.players if p.id != interaction.user.id]
        s.leaders = [p for p in s.leaders if p.id != interaction.user.id]
        await self._refresh(interaction)

    @discord.ui.button(label="음성채널 인원 불러오기", style=discord.ButtonStyle.secondary, emoji="🔊")
    async def from_voice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_host(interaction):
            await interaction.response.send_message("주최자만 사용할 수 있어요.", ephemeral=True)
            return
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            await interaction.response.send_message(
                "먼저 음성채널에 접속한 뒤 눌러주세요!", ephemeral=True
            )
            return
        s = self.session
        added = 0
        for m in voice.channel.members:
            if m.bot or any(p.id == m.id for p in s.players):
                continue
            if len(s.players) >= s.capacity:
                break
            s.players.append(m)
            added += 1
        await self._refresh(interaction)
        await interaction.followup.send(f"🔊 {added}명을 불러왔어요!", ephemeral=True)

    @discord.ui.button(label="팀장 지정", style=discord.ButtonStyle.primary, emoji="👑")
    async def set_leaders(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_host(interaction):
            await interaction.response.send_message("주최자만 지정할 수 있어요.", ephemeral=True)
            return
        s = self.session
        if len(s.players) < s.team_count:
            await interaction.response.send_message(
                f"참가자가 팀 수({s.team_count}명)보다 적어요!", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "팀장을 선택하세요:", view=LeaderSelectView(self), ephemeral=True
        )

    @discord.ui.button(label="시작", style=discord.ButtonStyle.danger, emoji="🚀")
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_host(interaction):
            await interaction.response.send_message("주최자만 시작할 수 있어요.", ephemeral=True)
            return
        s = self.session
        if len(s.players) < max(s.team_count, 2):
            await interaction.response.send_message(
                f"참가자가 부족해요! 최소 {max(s.team_count, 2)}명 필요.", ephemeral=True
            )
            return
        if s.mode != MODE_RANDOM and len(s.leaders) != s.team_count:
            await interaction.response.send_message(
                f"먼저 [팀장 지정] 버튼으로 팀장 {s.team_count}명을 지정해주세요!", ephemeral=True
            )
            return

        self.stop()
        if s.mode == MODE_RANDOM:
            self._random_assign()
            await interaction.response.edit_message(embed=teams_embed(s), view=None)
        elif s.mode == MODE_DRAFT:
            state = DraftState(s)
            if state.done:
                _assign_leftovers(s, state.pool)
                await interaction.response.edit_message(embed=teams_embed(s), view=None)
                return
            view = DraftView(state)
            await interaction.response.edit_message(embed=draft_embed(state), view=view)
            view.message = await interaction.original_response()
        else:  # 경매
            state = AuctionState(s)
            view = AuctionView(state)
            state.next_nominee()
            if state.nominee is None:
                await interaction.response.edit_message(embed=teams_embed(s), view=None)
                return
            await interaction.response.edit_message(embed=auction_embed(state), view=view)
            view.message = await interaction.original_response()
            view.start_timer()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_host(interaction):
            await interaction.response.send_message("주최자만 취소할 수 있어요.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content="❌ 팀짜기가 취소되었습니다.", embed=None, view=None
        )

    def _random_assign(self) -> None:
        s = self.session
        for i, leader in enumerate(s.leaders):
            s.teams[i].append(leader)
        pool = [p for p in s.players if p not in s.leaders]
        random.shuffle(pool)
        for p in pool:
            idx = min(range(s.team_count), key=lambda i: len(s.teams[i]))
            if len(s.teams[idx]) >= s.team_size:
                break
            s.teams[idx].append(p)


def _assign_leftovers(s: TeamSession, pool: list[discord.Member]) -> None:
    """남은 인원을 자리가 있는 팀에 순서대로 배정."""
    for p in list(pool):
        open_teams = [i for i in range(s.team_count) if len(s.teams[i]) < s.team_size]
        if not open_teams:
            break
        idx = min(open_teams, key=lambda i: len(s.teams[i]))
        s.teams[idx].append(p)
        pool.remove(p)


# ================================================================= 턴제 드래프트
class DraftState:
    def __init__(self, session: TeamSession) -> None:
        self.session = session
        for i, leader in enumerate(session.leaders):
            session.teams[i].append(leader)
        self.pool = [p for p in session.players if p not in session.leaders]
        random.shuffle(self.pool)

        rounds = max(session.team_size - 1, 0)
        idxs = list(range(session.team_count))
        self.order: list[int] = []
        for r in range(rounds):
            self.order.extend(idxs if r % 2 == 0 else list(reversed(idxs)))
        self.pos = 0
        self._skip_full()

    @property
    def done(self) -> bool:
        return not self.pool or self.pos >= len(self.order)

    def current_idx(self) -> int:
        return self.order[self.pos]

    def current_leader(self) -> discord.Member:
        return self.session.leaders[self.current_idx()]

    def _skip_full(self) -> None:
        s = self.session
        while self.pos < len(self.order) and len(s.teams[self.order[self.pos]]) >= s.team_size:
            self.pos += 1

    def pick(self, member: discord.Member) -> None:
        self.session.teams[self.current_idx()].append(member)
        self.pool.remove(member)
        self.pos += 1
        self._skip_full()


def draft_embed(state: DraftState) -> discord.Embed:
    s = state.session
    embed = teams_embed(s, title="🎯 턴제 드래프트 진행 중")
    embed.color = 0xE67E22
    embed.add_field(
        name="⏳ 남은 인원",
        value=", ".join(p.display_name for p in state.pool) or "-",
        inline=False,
    )
    embed.add_field(
        name="👉 현재 차례",
        value=f"{state.current_leader().mention} ({state.current_idx() + 1}팀) — 아래 메뉴에서 팀원을 선택하세요!",
        inline=False,
    )
    return embed


class PickSelect(discord.ui.Select):
    def __init__(self, state: DraftState) -> None:
        options = [
            discord.SelectOption(label=p.display_name[:100], value=str(p.id))
            for p in state.pool[:25]
        ]
        super().__init__(placeholder="팀원 선택...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: DraftView = self.view
        state = view.state
        member = next((p for p in state.pool if p.id == int(self.values[0])), None)
        if member is None:
            await interaction.response.send_message("이미 선택된 유저예요.", ephemeral=True)
            return
        state.pick(member)
        if state.done:
            _assign_leftovers(state.session, state.pool)
            view.stop()
            await interaction.response.edit_message(
                embed=teams_embed(state.session), view=None
            )
        else:
            view.rebuild()
            await interaction.response.edit_message(embed=draft_embed(state), view=view)


class DraftView(discord.ui.View):
    def __init__(self, state: DraftState) -> None:
        super().__init__(timeout=600)
        self.state = state
        self.message: Optional[discord.Message] = None
        self.rebuild()

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(PickSelect(self.state))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.state.current_leader().id:
            await interaction.response.send_message(
                f"지금은 {self.state.current_leader().display_name}님의 차례예요!",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        state = self.state
        random.shuffle(state.pool)
        _assign_leftovers(state.session, state.pool)
        if self.message:
            try:
                await self.message.edit(
                    embed=teams_embed(
                        state.session, title="⏰ 시간 초과 - 남은 인원은 자동 배정했어요!"
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass


# ================================================================= 경매
class AuctionState:
    def __init__(self, session: TeamSession) -> None:
        self.session = session
        for i, leader in enumerate(session.leaders):
            session.teams[i].append(leader)
        self.pool = [p for p in session.players if p not in session.leaders]
        random.shuffle(self.pool)
        self.budgets = [config.AUCTION_BUDGET] * session.team_count
        self.nominee: Optional[discord.Member] = None
        self.bid = 0
        self.bidder: Optional[int] = None
        self.passed: set[int] = set()
        self.finished = False
        self.log: list[str] = []

    def leader_idx(self, user_id: int) -> Optional[int]:
        for i, leader in enumerate(self.session.leaders):
            if leader.id == user_id:
                return i
        return None

    def eligible(self) -> list[int]:
        s = self.session
        return [i for i in range(s.team_count) if len(s.teams[i]) < s.team_size]

    def active(self) -> list[int]:
        return [i for i in self.eligible() if i not in self.passed]

    def should_resolve(self) -> bool:
        act = self.active()
        if self.bidder is not None:
            return all(i == self.bidder for i in act)
        return not act

    def next_nominee(self) -> Optional[discord.Member]:
        self.nominee = self.pool.pop(0) if self.pool and self.eligible() else None
        self.bid = 0
        self.bidder = None
        self.passed = set()
        return self.nominee

    def resolve(self) -> None:
        """현재 후보를 낙찰/유찰 처리."""
        if self.nominee is None:
            return
        if self.bidder is not None:
            idx, price = self.bidder, self.bid
            self.log.append(
                f"💰 **{self.nominee.display_name}** → {idx + 1}팀 ({price:,}💰 낙찰)"
            )
        else:
            elig = self.eligible()
            idx = min(elig, key=lambda i: (len(self.session.teams[i]), -self.budgets[i]))
            price = 0
            self.log.append(f"📦 **{self.nominee.display_name}** → {idx + 1}팀 (유찰, 무료 배정)")
        self.session.teams[idx].append(self.nominee)
        self.budgets[idx] -= price
        self.nominee = None


def auction_embed(state: AuctionState) -> discord.Embed:
    s = state.session
    embed = teams_embed(s, title="💸 경매 진행 중", budgets=state.budgets)
    embed.color = 0xF39C12
    if state.nominee:
        if state.bidder is not None:
            bid_info = f"현재 최고가: **{state.bid:,}💰** ({state.bidder + 1}팀 {s.leaders[state.bidder].display_name})"
        else:
            bid_info = "아직 입찰 없음 (모두 패스하면 인원이 적은 팀에 무료 배정)"
        embed.add_field(
            name=f"🔨 경매 중: {state.nominee.display_name}",
            value=(
                f"{state.nominee.mention}\n{bid_info}\n"
                f"⏱️ {AUCTION_TIMER}초간 입찰이 없으면 자동 확정됩니다."
            ),
            inline=False,
        )
    if state.log:
        embed.add_field(name="📜 경매 기록", value="\n".join(state.log[-5:]), inline=False)
    embed.add_field(
        name="⏳ 대기 인원",
        value=", ".join(p.display_name for p in state.pool) or "없음",
        inline=False,
    )
    embed.set_footer(text="팀장만 입찰/패스할 수 있습니다.")
    return embed


class AuctionView(discord.ui.View):
    def __init__(self, state: AuctionState) -> None:
        super().__init__(timeout=1800)
        self.state = state
        self.message: Optional[discord.Message] = None
        self.lock = asyncio.Lock()
        self.deadline = 0.0
        self.timer_task: Optional[asyncio.Task] = None

    def start_timer(self) -> None:
        loop = asyncio.get_running_loop()
        self.deadline = loop.time() + AUCTION_TIMER
        if self.timer_task is None:
            self.timer_task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.state.finished:
            await asyncio.sleep(2)
            async with self.lock:
                if self.state.finished:
                    break
                if loop.time() >= self.deadline:
                    await self._advance(None)

    async def _advance(self, interaction: Optional[discord.Interaction]) -> None:
        """현재 후보 확정 후 다음 후보로. (호출자가 lock을 잡고 있어야 함)"""
        state = self.state
        state.resolve()
        state.next_nominee()
        if state.nominee is None:
            state.finished = True
            _assign_leftovers(state.session, state.pool)
            self.stop()
            # 타이머 태스크가 자기 자신을 취소하면 마지막 메시지 수정이 끊기므로 제외
            if self.timer_task and self.timer_task is not asyncio.current_task():
                self.timer_task.cancel()
            embed = teams_embed(state.session, budgets=state.budgets)
            if state.log:
                embed.add_field(name="📜 경매 기록", value="\n".join(state.log[-10:]), inline=False)
            await self._edit(interaction, embed=embed, view=None)
            return
        self.deadline = asyncio.get_running_loop().time() + AUCTION_TIMER
        await self._edit(interaction, embed=auction_embed(state), view=self)

    async def _edit(self, interaction, **kwargs) -> None:
        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(**kwargs)
            elif self.message:
                await self.message.edit(**kwargs)
        except discord.HTTPException:
            pass

    async def _try_bid(self, interaction: discord.Interaction, step: int) -> None:
        async with self.lock:
            state = self.state
            if state.finished or state.nominee is None:
                await interaction.response.send_message("진행 중인 경매가 없어요.", ephemeral=True)
                return
            idx = state.leader_idx(interaction.user.id)
            if idx is None:
                await interaction.response.send_message("팀장만 입찰할 수 있어요!", ephemeral=True)
                return
            if idx not in state.eligible():
                await interaction.response.send_message("팀이 이미 가득 찼어요!", ephemeral=True)
                return
            if state.bidder == idx:
                await interaction.response.send_message("이미 최고 입찰자예요!", ephemeral=True)
                return
            new_bid = state.bid + step
            if state.budgets[idx] < new_bid:
                await interaction.response.send_message(
                    f"예산이 부족해요! (남은 예산 {state.budgets[idx]:,}💰)", ephemeral=True
                )
                return
            state.bid = new_bid
            state.bidder = idx
            state.passed.discard(idx)
            if state.should_resolve():
                await self._advance(interaction)
                return
            self.deadline = asyncio.get_running_loop().time() + AUCTION_TIMER
            await interaction.response.edit_message(embed=auction_embed(state), view=self)

    @discord.ui.button(label="+50", style=discord.ButtonStyle.primary, emoji="💰")
    async def bid_50(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._try_bid(interaction, 50)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.primary, emoji="💰")
    async def bid_100(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._try_bid(interaction, 100)

    @discord.ui.button(label="+250", style=discord.ButtonStyle.primary, emoji="💰")
    async def bid_250(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._try_bid(interaction, 250)

    @discord.ui.button(label="패스", style=discord.ButtonStyle.secondary, emoji="✋")
    async def pass_bid(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.lock:
            state = self.state
            if state.finished or state.nominee is None:
                await interaction.response.send_message("진행 중인 경매가 없어요.", ephemeral=True)
                return
            idx = state.leader_idx(interaction.user.id)
            if idx is None:
                await interaction.response.send_message("팀장만 패스할 수 있어요!", ephemeral=True)
                return
            if state.bidder == idx:
                await interaction.response.send_message(
                    "최고 입찰자는 패스할 수 없어요!", ephemeral=True
                )
                return
            state.passed.add(idx)
            if state.should_resolve():
                await self._advance(interaction)
                return
            await interaction.response.edit_message(embed=auction_embed(state), view=self)

    @discord.ui.button(label="강제 확정", style=discord.ButtonStyle.danger, emoji="⏭️")
    async def force_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.lock:
            if interaction.user.id != self.state.session.host.id:
                await interaction.response.send_message("주최자만 사용할 수 있어요.", ephemeral=True)
                return
            if self.state.finished:
                return
            await self._advance(interaction)

    async def on_timeout(self) -> None:
        state = self.state
        if state.finished:
            return
        state.finished = True
        if state.nominee:
            state.pool.insert(0, state.nominee)
        _assign_leftovers(state.session, state.pool)
        if self.timer_task:
            self.timer_task.cancel()
        if self.message:
            try:
                await self.message.edit(
                    embed=teams_embed(
                        state.session,
                        title="⏰ 시간 초과 - 남은 인원은 자동 배정했어요!",
                        budgets=state.budgets,
                    ),
                    view=None,
                )
            except discord.HTTPException:
                pass


# ================================================================= 코그
class TeamCog(commands.Cog, name="팀짜기"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="팀짜기", description="팀을 짜봅시다! 랜덤 / 턴제 드래프트 / 경매 방식 지원")
    @app_commands.guild_only()
    @app_commands.describe(
        팀수="몇 개의 팀으로 나눌까요? (2~8)",
        팀당인원="팀당 몇 명인가요? (1~10)",
        방식="팀원 배정 방식을 선택하세요.",
    )
    @app_commands.choices(
        방식=[
            app_commands.Choice(name="🎲 랜덤 - 무작위 배정", value=MODE_RANDOM),
            app_commands.Choice(name="🎯 턴제 드래프트 - 팀장이 번갈아 선택", value=MODE_DRAFT),
            app_commands.Choice(name="💸 경매 - 팀장이 예산으로 입찰", value=MODE_AUCTION),
        ]
    )
    @app_commands.checks.cooldown(2, 30.0, key=lambda i: (i.guild_id, i.user.id))
    async def team_build(
        self,
        interaction: discord.Interaction,
        팀수: app_commands.Range[int, 2, 8],
        팀당인원: app_commands.Range[int, 1, 10],
        방식: app_commands.Choice[str],
    ) -> None:
        mode = 방식.value
        capacity = 팀수 * 팀당인원
        if mode != MODE_RANDOM and capacity > 25:
            await interaction.response.send_message(
                "턴제 드래프트/경매 방식은 최대 25명까지 지원해요. "
                "(디스코드 선택 메뉴 제한) 더 큰 규모는 랜덤 방식을 사용해주세요!",
                ephemeral=True,
            )
            return
        session = TeamSession(interaction.user, 팀수, 팀당인원, mode)
        view = LobbyView(session)
        await interaction.response.send_message(embed=lobby_embed(session), view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TeamCog(bot))
