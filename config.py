"""봇 설정 - .env 파일에서 환경변수를 읽어옵니다."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "").strip()
PUBG_API_KEY = os.getenv("PUBG_API_KEY", "").strip()
HENRIK_API_KEY = os.getenv("HENRIK_API_KEY", "").strip()
KOREANBOTS_TOKEN = os.getenv("KOREANBOTS_TOKEN", "").strip()

_test_guild = os.getenv("TEST_GUILD_ID", "").strip()
TEST_GUILD_ID = int(_test_guild) if _test_guild.isdigit() else 0

OWNER_IDS = {
    int(x)
    for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",")
    if x.isdigit()
}

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

# 경제 설정
STARTING_COINS = 5000     # 신규 유저 시작 잔액
DAILY_BASE = 100          # 출석 기본 보상
DAILY_STREAK_BONUS = 20   # 연속 출석 1일당 추가 보상
DAILY_STREAK_CAP = 10     # 연속 보너스 최대 일수
VOTE_REWARD = 300         # koreanbots 하트 투표 보상
TRANSFER_FEE = 0.05       # 송금 수수료 (5%)

# 갓챠 설정
GACHA_COST = 100          # 1회 뽑기 비용
GACHA_TEN_COST = 900      # 10연차 비용 (10% 할인)
PITY_LIMIT = 90           # 천장: 이 횟수 안에 전설 이상 보장

# 팀 경매 설정
AUCTION_BUDGET = 1000     # 경매 방식 팀장 기본 예산
