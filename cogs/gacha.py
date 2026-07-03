"""갓챠(뽑기) 시스템 + 미니게임.

- 등급: 일반/고급/희귀/영웅/전설/신화
- 천장(pity): 90회 안에 전설 이상 보장
- 10연차: 희귀 이상 1개 보장 + 10% 할인
- 실제 화폐와 무관한 가상 재화(코인)만 사용합니다.
"""
from __future__ import annotations

import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config

COIN = "🪙"

# (등급, 확률(%), 색상, 이모지, 판매가)
RARITIES: list[tuple[str, float, int, str, int]] = [
    ("일반", 50.0, 0x95A5A6, "⚪", 10),
    ("고급", 25.0, 0x2ECC71, "🟢", 30),
    ("희귀", 15.0, 0x3498DB, "🔵", 80),
    ("영웅", 7.0, 0x9B59B6, "🟣", 250),
    ("전설", 2.5, 0xF1C40F, "🟡", 1000),
    ("신화", 0.5, 0xE74C3C, "🔴", 5000),
]
RARITY_INDEX = {r[0]: i for i, r in enumerate(RARITIES)}
RARITY_EMOJI = {r[0]: r[3] for r in RARITIES}
RARITY_COLOR = {r[0]: r[2] for r in RARITIES}
SELL_PRICE = {r[0]: r[4] for r in RARITIES}

ITEMS: dict[str, list[str]] = {
    "일반": ["포션 조각", "와드 껍데기", "미니언 인형", "낡은 장화", "훈련용 더미", "서포터의 동전", "빛바랜 카드", "구부러진 검"],
    "고급": ["롱소드", "요정의 부적", "붉은 물약 세트", "푸른 파수꾼 조각", "어둠의 인장", "곡괭이"],
    "희귀": ["무한의 대검 조각", "죽음모자 파편", "수호천사 깃털", "드래곤의 비늘", "바론의 송곳니", "장로의 숨결"],
    "영웅": ["펜타킬 트로피", "챌린저의 문장", "전설급 스킨 상자", "우승 트로피 레플리카", "프로게이머의 사인"],
    "전설": ["소환사의 컵", "롤드컵 우승 반지", "한정판 황금 와드", "전설의 미드라이너 키보드"],
    "신화": ["넥서스의 심장", "시공의 열쇠", "데마시아의 왕관"],
}
ITEM_RARITY = {name: rarity for rarity, names in ITEMS.items() for name in names}
TOTAL_ITEMS = sum(len(v) for v in ITEMS.values())

EPIC_PLUS = ("전설", "신화")  # 천장 대상 등급

# 슬롯 심볼: (이모지, 가중치, 3개 일치 배수)
SLOT_SYMBOLS = [("🍒", 30, 3), ("🍋", 25, 4), ("🔔", 20, 6), ("💎", 15, 10), ("7️⃣", 10, 20)]


def roll_rarity(pity: int) -> str:
    """등급 결정. pity(전설+ 미획득 누적 횟수)가 천장에 도달하면 전설+ 확정."""
    if pity + 1 >= config.PITY_LIMIT:
        return "신화" if random.random() < 1 / 6 else "전설"
    r = random.uniform(0, 100)
    acc = 0.0
    for name, weight, *_ in RARITIES:
        acc += weight
        if r <= acc:
            return name
    return "일반"


def roll_item(rarity: str) -> str:
    return random.choice(ITEMS[rarity])


class GachaCog(commands.Cog, name="뽑기"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------- 뽑기
    @app_commands.command(name="뽑기", description=f"코인으로 아이템을 뽑아보세요! (1회 {config.GACHA_COST}코인)")
    @app_commands.describe(종류="10연차는 10% 할인 + 희귀 이상 1개 보장!")
    @app_commands.choices(
        종류=[
            app_commands.Choice(name=f"1회 뽑기 ({config.GACHA_COST}코인)", value=1),
            app_commands.Choice(name=f"10연차 ({config.GACHA_TEN_COST}코인)", value=10),
        ]
    )
    @app_commands.checks.cooldown(5, 30.0, key=lambda i: i.user.id)
    async def pull(self, interaction: discord.Interaction, 종류: app_commands.Choice[int]) -> None:
        count = 종류.value
        cost = config.GACHA_COST if count == 1 else config.GACHA_TEN_COST
        if not await self.db.try_spend(interaction.user.id, cost):
            coins = await self.db.get_coins(interaction.user.id)
            await interaction.response.send_message(
                f"코인이 부족해요! 필요: {cost:,} / 보유: {coins:,}\n"
                "`/출석`, `/투표보상` 으로 코인을 모아보세요!",
                ephemeral=True,
            )
            return

        pity_row = await self.db.get_pity(interaction.user.id)
        pity = pity_row["since_epic"]
        owned = {row["item_key"] for row in await self.db.get_inventory(interaction.user.id)}

        results: list[tuple[str, str]] = []  # (rarity, item)
        for _ in range(count):
            rarity = roll_rarity(pity)
            pity = 0 if rarity in EPIC_PLUS else pity + 1
            results.append((rarity, roll_item(rarity)))

        # 10연차 보장: 희귀 이상이 없으면 마지막 결과를 희귀로 승급
        if count == 10 and all(RARITY_INDEX[r] < RARITY_INDEX["희귀"] for r, _ in results):
            results[-1] = ("희귀", roll_item("희귀"))

        for rarity, item in results:
            await self.db.add_item(interaction.user.id, item)
        await self.db.set_pity(interaction.user.id, pity, count)

        best = max(results, key=lambda x: RARITY_INDEX[x[0]])
        lines = []
        for rarity, item in results:
            new = " ✨NEW" if item not in owned else ""
            owned.add(item)
            lines.append(f"{RARITY_EMOJI[rarity]} **[{rarity}]** {item}{new}")

        balance = await self.db.get_coins(interaction.user.id)
        embed = discord.Embed(
            title=f"🎁 {interaction.user.display_name}님의 뽑기 결과",
            description="\n".join(lines),
            color=RARITY_COLOR[best[0]],
        )
        embed.set_footer(
            text=f"잔액 {balance:,}코인 · 천장까지 {max(config.PITY_LIMIT - pity, 0)}회 (전설+ 보장)"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="천장", description="뽑기 천장(전설 보장)까지 남은 횟수를 확인합니다.")
    async def pity_status(self, interaction: discord.Interaction) -> None:
        row = await self.db.get_pity(interaction.user.id)
        remain = max(config.PITY_LIMIT - row["since_epic"], 0)
        await interaction.response.send_message(
            f"🎯 천장까지 **{remain}회** 남았어요! (누적 뽑기 {row['total_pulls']:,}회)\n"
            f"{config.PITY_LIMIT}회 안에 전설 이상 등급이 보장됩니다.",
            ephemeral=True,
        )

    @app_commands.command(name="인벤토리", description="보유한 아이템을 확인합니다.")
    @app_commands.describe(유저="다른 유저의 인벤토리를 구경할 수 있어요.")
    async def inventory(
        self, interaction: discord.Interaction, 유저: Optional[discord.User] = None
    ) -> None:
        target = 유저 or interaction.user
        rows = await self.db.get_inventory(target.id)
        if not rows:
            await interaction.response.send_message(
                f"{target.display_name}님의 인벤토리가 비어있어요. `/뽑기` 로 시작해보세요!",
                ephemeral=True,
            )
            return

        by_rarity: dict[str, list[str]] = {}
        for row in rows:
            rarity = ITEM_RARITY.get(row["item_key"], "일반")
            by_rarity.setdefault(rarity, []).append(f"{row['item_key']} x{row['count']}")

        embed = discord.Embed(
            title=f"🎒 {target.display_name}님의 인벤토리",
            color=0x3498DB,
        )
        for rarity, *_ in reversed(RARITIES):
            if rarity in by_rarity:
                embed.add_field(
                    name=f"{RARITY_EMOJI[rarity]} {rarity}",
                    value="\n".join(by_rarity[rarity])[:1024],
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="도감", description="아이템 수집 현황을 확인합니다.")
    async def collection(self, interaction: discord.Interaction) -> None:
        rows = await self.db.get_inventory(interaction.user.id)
        owned = {row["item_key"] for row in rows}
        lines = []
        total_owned = 0
        for rarity, *_ in reversed(RARITIES):
            pool = ITEMS[rarity]
            got = sum(1 for item in pool if item in owned)
            total_owned += got
            bar = "■" * got + "□" * (len(pool) - got)
            lines.append(f"{RARITY_EMOJI[rarity]} **{rarity}** {bar} {got}/{len(pool)}")
        pct = total_owned / TOTAL_ITEMS * 100
        embed = discord.Embed(
            title=f"📖 {interaction.user.display_name}님의 도감",
            description="\n".join(lines) + f"\n\n전체 수집률: **{pct:.1f}%** ({total_owned}/{TOTAL_ITEMS})",
            color=0x9B59B6,
        )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------- 판매
    async def sell_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = await self.db.get_inventory(interaction.user.id)
        choices = []
        for row in rows:
            item = row["item_key"]
            if current and current not in item:
                continue
            rarity = ITEM_RARITY.get(item, "일반")
            choices.append(
                app_commands.Choice(
                    name=f"[{rarity}] {item} (x{row['count']}, 개당 {SELL_PRICE[rarity]}코인)",
                    value=item,
                )
            )
        return choices[:25]

    @app_commands.command(name="판매", description="아이템을 팔아 코인으로 바꿉니다.")
    @app_commands.describe(아이템="판매할 아이템", 수량="판매 수량 (기본 1개)")
    @app_commands.autocomplete(아이템=sell_autocomplete)
    async def sell(
        self,
        interaction: discord.Interaction,
        아이템: str,
        수량: app_commands.Range[int, 1, 999] = 1,
    ) -> None:
        rarity = ITEM_RARITY.get(아이템)
        if not rarity:
            await interaction.response.send_message("존재하지 않는 아이템이에요.", ephemeral=True)
            return
        if not await self.db.remove_item(interaction.user.id, 아이템, 수량):
            have = await self.db.get_item_count(interaction.user.id, 아이템)
            await interaction.response.send_message(
                f"수량이 부족해요! 보유: {have}개", ephemeral=True
            )
            return
        earned = SELL_PRICE[rarity] * 수량
        balance = await self.db.add_coins(interaction.user.id, earned)
        await interaction.response.send_message(
            f"💰 {RARITY_EMOJI[rarity]} **{아이템}** x{수량} 판매 완료! "
            f"{COIN} **+{earned:,}** (잔액 {balance:,})"
        )

    # ------------------------------------------------------------- 미니게임
    @app_commands.command(name="동전던지기", description="앞면/뒷면을 맞히면 배팅한 코인의 2배!")
    @app_commands.describe(선택="앞면 또는 뒷면", 배팅="배팅할 코인")
    @app_commands.choices(
        선택=[
            app_commands.Choice(name="앞면", value="앞면"),
            app_commands.Choice(name="뒷면", value="뒷면"),
        ]
    )
    @app_commands.checks.cooldown(3, 15.0, key=lambda i: i.user.id)
    async def coinflip(
        self,
        interaction: discord.Interaction,
        선택: app_commands.Choice[str],
        배팅: app_commands.Range[int, 10, 10_000],
    ) -> None:
        if not await self.db.try_spend(interaction.user.id, 배팅):
            coins = await self.db.get_coins(interaction.user.id)
            await interaction.response.send_message(
                f"코인이 부족해요! 보유: {coins:,}", ephemeral=True
            )
            return
        result = random.choice(["앞면", "뒷면"])
        win = result == 선택.value
        if win:
            balance = await self.db.add_coins(interaction.user.id, 배팅 * 2)
            msg = f"🎉 **{result}**! 정답! {COIN} **+{배팅:,}** (잔액 {balance:,})"
            color = 0x2ECC71
        else:
            balance = await self.db.get_coins(interaction.user.id)
            msg = f"💥 **{result}**... 아쉬워요! {COIN} **-{배팅:,}** (잔액 {balance:,})"
            color = 0xE74C3C
        embed = discord.Embed(description=f"🪙 동전을 던졌습니다!\n\n{msg}", color=color)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="슬롯", description="슬롯머신을 돌려보세요! 3개 일치 시 최대 20배!")
    @app_commands.describe(배팅="배팅할 코인")
    @app_commands.checks.cooldown(3, 15.0, key=lambda i: i.user.id)
    async def slots(
        self,
        interaction: discord.Interaction,
        배팅: app_commands.Range[int, 10, 10_000],
    ) -> None:
        if not await self.db.try_spend(interaction.user.id, 배팅):
            coins = await self.db.get_coins(interaction.user.id)
            await interaction.response.send_message(
                f"코인이 부족해요! 보유: {coins:,}", ephemeral=True
            )
            return
        symbols = [s for s, _, _ in SLOT_SYMBOLS]
        weights = [w for _, w, _ in SLOT_SYMBOLS]
        payouts = {s: p for s, _, p in SLOT_SYMBOLS}
        reels = random.choices(symbols, weights=weights, k=3)
        display = " | ".join(reels)

        if reels[0] == reels[1] == reels[2]:
            mult = payouts[reels[0]]
            won = 배팅 * mult
            balance = await self.db.add_coins(interaction.user.id, won)
            msg = f"🎰 잭팟! **{mult}배**! {COIN} **+{won - 배팅:,}** (잔액 {balance:,})"
            color = 0xF1C40F
        elif len(set(reels)) == 2:
            won = int(배팅 * 1.5)
            balance = await self.db.add_coins(interaction.user.id, won)
            msg = f"✨ 2개 일치! 1.5배! {COIN} **+{won - 배팅:,}** (잔액 {balance:,})"
            color = 0x2ECC71
        else:
            balance = await self.db.get_coins(interaction.user.id)
            msg = f"💨 꽝... {COIN} **-{배팅:,}** (잔액 {balance:,})"
            color = 0x95A5A6
        embed = discord.Embed(
            title=f"🎰 [ {display} ]",
            description=msg,
            color=color,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GachaCog(bot))
