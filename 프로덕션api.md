# Riot 프로덕션 API 신청서 작성 내용

> 아래 내용을 https://developer.riotgames.com 의 "Register Product" 폼에 그대로 붙여넣으면 됩니다.
> 심사는 Riot 본사에서 하므로 영어로 제출하는 것을 권장합니다. (한국어 번역은 참고용)

---

## Product Name

```
TeamVS
```

## Product Description

```
TeamVS is a Korean-language Discord bot focused on team-building for game
communities. Its core feature splits voice-channel members into balanced teams
(random, turn-based draft, or auction draft) for custom games. To make team
balancing meaningful, the bot lets each user link their Riot ID and shows
their League of Legends profile and a "combat power" score calculated from
their recent performance, plus a per-server leaderboard.

How it works:
1. A user runs the /롤 등록 (register) command with their Riot ID
   (gameName#tagLine). We call ACCOUNT-V1 (by-riot-id) once to resolve it to
   a PUUID and store only the PUUID linked to the user's Discord ID, with the
   user's consent. Users can unlink at any time with the /롤 해제 (unregister)
   command, which deletes the stored data.
2. The /롤 전적 (profile) command calls SUMMONER-V4 (level, profile icon),
   LEAGUE-V4 (ranked entries), CHAMPION-MASTERY-V4 (top masteries), and
   MATCH-V5 (recent 10 matches) and displays them as a Discord embed.
3. The /롤 전투력 (combat power) command analyzes the recent matches from
   MATCH-V5 together with LEAGUE-V4 rank data to produce a fun, informal
   score that feeds a per-server ranking (/롤 랭킹) and helps the team
   splitter create balanced teams.
4. Champion names and images are loaded from Data Dragon (Korean locale).

APIs used: ACCOUNT-V1, SUMMONER-V4, LEAGUE-V4, MATCH-V5, CHAMPION-MASTERY-V4,
and Data Dragon for static data.

Rate-limit handling: all requests go through a single client that honors the
Retry-After header on HTTP 429; results are requested on demand (only when a
user runs a command) and match details are fetched at most 10 per command.
Commands have per-user cooldowns to keep request volume low.

Data handling: we store only the PUUID mapped to a Discord user ID and the
computed score. No match data is resold or redistributed; nothing is shown
that is not available to the user in the game client. The bot is free to use,
has no paid features, and is not affiliated with or endorsed by Riot Games.

TeamVS is publicly listed on the Korean Discord bot directory (koreanbots.dev),
and the product URL below is its public listing page.
```

### (참고용 한국어 번역)

> TeamVS는 게임 커뮤니티를 위한 팀 구성 특화 한국어 디스코드 봇입니다.
> 핵심 기능은 음성채널 멤버를 랜덤/턴제 드래프트/경매 방식으로 균형 있게
> 나누는 것이고, 밸런스에 참고할 수 있도록 라이엇 계정 연동(전적/전투력/서버
> 랭킹) 기능을 제공합니다.
>
> 1. `/롤 등록` — Riot ID를 ACCOUNT-V1로 PUUID로 변환해 디스코드 ID와
>    연결하여 저장 (본인 동의 기반, `/롤 해제`로 언제든 삭제 가능)
> 2. `/롤 전적` — SUMMONER-V4(레벨·아이콘), LEAGUE-V4(랭크),
>    CHAMPION-MASTERY-V4(숙련도), MATCH-V5(최근 10경기)를 임베드로 표시
> 3. `/롤 전투력` — 최근 경기 + 랭크를 분석해 재미용 점수 산출, 서버
>    랭킹(`/롤 랭킹`)과 팀 밸런싱에 활용
> 4. 챔피언 이름/이미지는 Data Dragon(ko_KR) 사용
>
> 429 응답 시 Retry-After 준수, 명령어별 쿨다운으로 요청량 최소화,
> PUUID와 점수만 저장하며 데이터 재판매/재배포 없음, 무료 봇.

## Product Group

```
Default Group
```

(혼자 개발한다면 Default Group 그대로 두면 됩니다. 다른 개발자를 초대해야
할 때만 새 그룹을 만드세요.)

## Product URL

```
https://koreanbots.dev/bots/1522644723448152165
```

(봇 ID = 디스코드 애플리케이션 ID. 위 값은 봇 토큰에서 확인한 실제 ID입니다.)

⚠️ **제출 전 브라우저에서 위 URL이 실제로 열리는지 확인하세요.**
koreanbots.dev 심사가 아직 안 끝났다면 페이지가 없을 수 있습니다. 그 경우
등록 승인을 먼저 받거나, 봇 소개가 담긴 공개 GitHub 저장소 README 주소를
대신 사용하세요. 접속되지 않는 URL을 넣으면 반려됩니다.

## Product Game Focus

```
League of Legends
```

(폼에 게임 선택 항목이 있으면 League of Legends 선택. 여러 게임을 지원해도
Riot API를 쓰는 게임은 롤뿐이므로 이것 하나만 등록하면 됩니다 — 배그/옵치/
발로란트 전적은 Riot LoL API와 무관. 단, 발로란트 기능에 Riot의 VAL API를
쓰게 된다면 그때 별도 제품으로 다시 등록해야 합니다.)

## Are you organizing tournaments?

```
No
```

(팀짜기는 사설 내전용 팀 분배 기능일 뿐 상금·참가비가 있는 토너먼트 운영이
아니므로 No. Yes를 선택하면 Tournament API 심사로 넘어가 훨씬 까다로워집니다.)

---

### 제출 전 체크리스트

- [ ] Product URL이 실제로 접속되는지 확인 (koreanbots 봇 페이지 권장)
- [ ] 개발자 포털 계정 이메일 인증 완료
- [ ] 신청 후 심사는 보통 2주 이상 걸릴 수 있음 — 그동안은 개발 키(24시간
      갱신)로 운영
- [ ] 승인 후 발급되는 프로덕션 키를 `.env`의 `RIOT_API_KEY`에 교체
