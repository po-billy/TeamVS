"""SQLite 데이터베이스 - 유저 경제, 롤 계정 연동, 갓챠 인벤토리, 서버 설정."""
from __future__ import annotations

from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    coins           INTEGER NOT NULL DEFAULT 0,
    last_daily      TEXT,
    daily_streak    INTEGER NOT NULL DEFAULT 0,
    last_vote_claim INTEGER NOT NULL DEFAULT 0
);

-- 게임별 계정 연동 (game: 'lol', 'valorant', 'pubg' ... 확장 가능)
CREATE TABLE IF NOT EXISTS game_accounts (
    user_id      INTEGER NOT NULL,
    game         TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    account_name TEXT NOT NULL,
    power        INTEGER NOT NULL DEFAULT 0,
    power_detail TEXT,
    updated_at   TEXT,
    PRIMARY KEY (user_id, game)
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id  INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_key)
);

CREATE TABLE IF NOT EXISTS gacha_pity (
    user_id     INTEGER PRIMARY KEY,
    since_epic  INTEGER NOT NULL DEFAULT 0,
    total_pulls INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id           INTEGER PRIMARY KEY,
    welcome_channel_id INTEGER,
    welcome_message    TEXT,
    log_channel_id     INTEGER
);
"""


class Database:
    def __init__(self, path, starting_coins: int = 0) -> None:
        self.path = str(path)
        self.starting_coins = starting_coins  # 신규 유저 시작 잔액
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate()
        await self.conn.commit()

    async def _migrate(self) -> None:
        """구버전 lol_accounts 테이블이 있으면 game_accounts로 이전."""
        async with self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lol_accounts'"
        ) as cur:
            if not await cur.fetchone():
                return
        await self.conn.execute(
            """INSERT OR IGNORE INTO game_accounts
                 (user_id, game, account_id, account_name, power, power_detail, updated_at)
               SELECT user_id, 'lol', puuid, game_name || '#' || tag_line,
                      power, power_detail, updated_at
               FROM lol_accounts"""
        )
        await self.conn.execute("DROP TABLE lol_accounts")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ------------------------------------------------------------- 유저/코인
    async def ensure_user(self, user_id: int) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, ?)",
            (user_id, self.starting_coins),
        )
        await self.conn.commit()
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()

    async def get_coins(self, user_id: int) -> int:
        row = await self.ensure_user(user_id)
        return row["coins"]

    async def add_coins(self, user_id: int, amount: int) -> int:
        """코인 지급(음수 가능). 새 잔액을 반환합니다."""
        await self.ensure_user(user_id)
        await self.conn.execute(
            "UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?",
            (amount, user_id),
        )
        await self.conn.commit()
        return await self.get_coins(user_id)

    async def try_spend(self, user_id: int, amount: int) -> bool:
        """잔액이 충분할 때만 차감. 성공 여부를 반환합니다 (원자적)."""
        await self.ensure_user(user_id)
        cur = await self.conn.execute(
            "UPDATE users SET coins = coins - ? WHERE user_id = ? AND coins >= ?",
            (amount, user_id, amount),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def top_coins(self, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

    async def set_daily(self, user_id: int, date_str: str, streak: int) -> None:
        await self.ensure_user(user_id)
        await self.conn.execute(
            "UPDATE users SET last_daily = ?, daily_streak = ? WHERE user_id = ?",
            (date_str, streak, user_id),
        )
        await self.conn.commit()

    async def set_vote_claim(self, user_id: int, last_vote_ts: int) -> None:
        await self.ensure_user(user_id)
        await self.conn.execute(
            "UPDATE users SET last_vote_claim = ? WHERE user_id = ?",
            (last_vote_ts, user_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------- 게임 계정
    async def link_account(
        self, user_id: int, game: str, account_id: str, account_name: str
    ) -> None:
        await self.conn.execute(
            """INSERT INTO game_accounts (user_id, game, account_id, account_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, game) DO UPDATE SET
                 account_id = excluded.account_id,
                 account_name = excluded.account_name,
                 power = 0, power_detail = NULL, updated_at = NULL""",
            (user_id, game, account_id, account_name),
        )
        await self.conn.commit()

    async def unlink_account(self, user_id: int, game: str) -> None:
        await self.conn.execute(
            "DELETE FROM game_accounts WHERE user_id = ? AND game = ?",
            (user_id, game),
        )
        await self.conn.commit()

    async def get_account(self, user_id: int, game: str) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM game_accounts WHERE user_id = ? AND game = ?",
            (user_id, game),
        ) as cur:
            return await cur.fetchone()

    async def update_power(
        self, user_id: int, game: str, power: int, detail: str, updated_at: str
    ) -> None:
        await self.conn.execute(
            """UPDATE game_accounts
               SET power = ?, power_detail = ?, updated_at = ?
               WHERE user_id = ? AND game = ?""",
            (power, detail, updated_at, user_id, game),
        )
        await self.conn.commit()

    async def all_powers(self, game: str) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM game_accounts WHERE game = ? AND power > 0 ORDER BY power DESC",
            (game,),
        ) as cur:
            return await cur.fetchall()

    # ------------------------------------------------------------- 갓챠
    async def add_item(self, user_id: int, item_key: str, n: int = 1) -> None:
        await self.conn.execute(
            """INSERT INTO inventory (user_id, item_key, count) VALUES (?, ?, ?)
               ON CONFLICT(user_id, item_key) DO UPDATE SET
                 count = count + excluded.count""",
            (user_id, item_key, n),
        )
        await self.conn.commit()

    async def remove_item(self, user_id: int, item_key: str, n: int = 1) -> bool:
        """보유 수량이 충분할 때만 차감 (원자적)."""
        cur = await self.conn.execute(
            """UPDATE inventory SET count = count - ?
               WHERE user_id = ? AND item_key = ? AND count >= ?""",
            (n, user_id, item_key, n),
        )
        await self.conn.commit()
        if cur.rowcount > 0:
            await self.conn.execute(
                "DELETE FROM inventory WHERE user_id = ? AND item_key = ? AND count <= 0",
                (user_id, item_key),
            )
            await self.conn.commit()
            return True
        return False

    async def get_inventory(self, user_id: int) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT item_key, count FROM inventory WHERE user_id = ? AND count > 0",
            (user_id,),
        ) as cur:
            return await cur.fetchall()

    async def get_item_count(self, user_id: int, item_key: str) -> int:
        async with self.conn.execute(
            "SELECT count FROM inventory WHERE user_id = ? AND item_key = ?",
            (user_id, item_key),
        ) as cur:
            row = await cur.fetchone()
            return row["count"] if row else 0

    async def get_pity(self, user_id: int) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO gacha_pity (user_id) VALUES (?)", (user_id,)
        )
        await self.conn.commit()
        async with self.conn.execute(
            "SELECT * FROM gacha_pity WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone()

    async def set_pity(self, user_id: int, since_epic: int, add_pulls: int) -> None:
        await self.get_pity(user_id)
        await self.conn.execute(
            """UPDATE gacha_pity
               SET since_epic = ?, total_pulls = total_pulls + ?
               WHERE user_id = ?""",
            (since_epic, add_pulls, user_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------- 서버 설정
    async def get_guild_settings(self, guild_id: int) -> Optional[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            return await cur.fetchone()

    async def set_welcome(
        self, guild_id: int, channel_id: Optional[int], message: Optional[str]
    ) -> None:
        await self.conn.execute(
            """INSERT INTO guild_settings (guild_id, welcome_channel_id, welcome_message)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 welcome_channel_id = excluded.welcome_channel_id,
                 welcome_message = excluded.welcome_message""",
            (guild_id, channel_id, message),
        )
        await self.conn.commit()

    async def set_log_channel(self, guild_id: int, channel_id: Optional[int]) -> None:
        await self.conn.execute(
            """INSERT INTO guild_settings (guild_id, log_channel_id) VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 log_channel_id = excluded.log_channel_id""",
            (guild_id, channel_id),
        )
        await self.conn.commit()
