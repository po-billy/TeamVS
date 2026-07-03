"""전투력 계산 로직.

전투력 = 랭크 점수 + 승률 보너스 + 최근 폼(KDA/최근 승률) + 레벨 보너스

랭크 점수 기준표 (솔로랭크 기준, 자유랭크만 있으면 90% 반영):
  아이언 0 / 브론즈 400 / 실버 800 / 골드 1200 / 플래티넘 1600
  에메랄드 2000 / 다이아 2400 / 마스터+ 2800 + LP
  각 티어 내 단계(IV~I)당 +100, LP 그대로 합산
"""
from __future__ import annotations

TIER_BASE = {
    "IRON": 0,
    "BRONZE": 400,
    "SILVER": 800,
    "GOLD": 1200,
    "PLATINUM": 1600,
    "EMERALD": 2000,
    "DIAMOND": 2400,
    "MASTER": 2800,
    "GRANDMASTER": 2800,
    "CHALLENGER": 2800,
}
DIVISION = {"IV": 0, "III": 100, "II": 200, "I": 300}
APEX_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}

TIER_KO = {
    "IRON": "아이언",
    "BRONZE": "브론즈",
    "SILVER": "실버",
    "GOLD": "골드",
    "PLATINUM": "플래티넘",
    "EMERALD": "에메랄드",
    "DIAMOND": "다이아몬드",
    "MASTER": "마스터",
    "GRANDMASTER": "그랜드마스터",
    "CHALLENGER": "챌린저",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rank_score(entry: dict | None) -> int:
    """LEAGUE-V4 엔트리 하나의 랭크 점수."""
    if not entry:
        return 0
    tier = entry.get("tier", "")
    base = TIER_BASE.get(tier)
    if base is None:
        return 0
    lp = entry.get("leaguePoints", 0)
    if tier in APEX_TIERS:
        return base + 300 + lp
    return base + DIVISION.get(entry.get("rank", "IV"), 0) + lp


def format_rank(entry: dict | None) -> str:
    """랭크 엔트리를 '골드 II 45LP (승률 54%)' 형태로 표시."""
    if not entry:
        return "언랭크"
    tier_ko = TIER_KO.get(entry.get("tier", ""), entry.get("tier", "?"))
    wins, losses = entry.get("wins", 0), entry.get("losses", 0)
    total = wins + losses
    wr = f" (승률 {wins / total * 100:.0f}%)" if total else ""
    if entry.get("tier") in APEX_TIERS:
        return f"{tier_ko} {entry.get('leaguePoints', 0)}LP{wr}"
    return f"{tier_ko} {entry.get('rank', '')} {entry.get('leaguePoints', 0)}LP{wr}"


def compute_power(
    solo: dict | None,
    flex: dict | None,
    level: int,
    recent: dict | None,
) -> tuple[int, list[str]]:
    """전투력과 상세 내역을 반환합니다.

    recent: {"games": n, "wins": n, "kills": n, "deaths": n, "assists": n}
    """
    breakdown: list[str] = []
    power = 0.0

    # 1) 랭크 점수 (솔랭 우선, 없으면 자랭 90%)
    if solo:
        rs = rank_score(solo)
        power += rs
        breakdown.append(f"🏆 솔로랭크 {format_rank(solo)} → **+{rs:,}**")
    elif flex:
        rs = int(rank_score(flex) * 0.9)
        power += rs
        breakdown.append(f"🏆 자유랭크 {format_rank(flex)} (90% 반영) → **+{rs:,}**")
    else:
        power += 500
        breakdown.append("🏆 언랭크 기본 점수 → **+500**")

    # 2) 랭크 승률 보너스
    main = solo or flex
    if main:
        wins, losses = main.get("wins", 0), main.get("losses", 0)
        total = wins + losses
        if total >= 10:
            wr = wins / total
            bonus = int(_clamp((wr - 0.5) * 1000, -150, 300))
            power += bonus
            sign = "+" if bonus >= 0 else ""
            breakdown.append(f"📈 랭크 승률 {wr * 100:.1f}% → **{sign}{bonus:,}**")

    # 3) 최근 폼 (최근 매치 KDA + 승률)
    if recent and recent.get("games", 0) > 0:
        games = recent["games"]
        deaths = max(recent["deaths"], 1)
        kda = (recent["kills"] + recent["assists"]) / deaths
        kda_bonus = int(_clamp(kda * 40, 0, 200))
        power += kda_bonus
        breakdown.append(f"⚔️ 최근 {games}게임 KDA {kda:.2f} → **+{kda_bonus:,}**")

        rwr = recent["wins"] / games
        form_bonus = int(_clamp((rwr - 0.5) * 400, -100, 200))
        power += form_bonus
        sign = "+" if form_bonus >= 0 else ""
        breakdown.append(f"🔥 최근 승률 {rwr * 100:.0f}% → **{sign}{form_bonus:,}**")

    # 4) 레벨 보너스
    lv_bonus = int(_clamp(level * 0.5, 0, 250))
    power += lv_bonus
    breakdown.append(f"⭐ 소환사 레벨 {level} → **+{lv_bonus:,}**")

    return max(int(power), 1), breakdown
