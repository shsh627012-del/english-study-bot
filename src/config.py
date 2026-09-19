"""전역 설정. 값을 바꾸고 싶으면 대부분 이 파일만 고치면 된다."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# ── 경로 ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data"
AUDIO = DOCS / "audio"
TMP = ROOT / ".tmp"

EXPRESSIONS_FILE = DATA / "expressions.json"
SRS_FILE = DATA / "srs.json"
KNOWN_FILE = DATA / "known.json"
INBOX_FILE = DATA / "inbox.json"
STATE_FILE = DATA / "state.json"
LOG_FILE = DATA / "log.jsonl"
CANDIDATES_FILE = DATA / "candidates.json"
CANDIDATE_STATUS_FILE = DATA / "candidate_status.json"   # 2MB 짜리 후보 파일을 매번 다시 쓰지 않도록 분리

# ── 시크릿 ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MERRIAM_WEBSTER_KEY = os.getenv("MERRIAM_WEBSTER_KEY", "")

# ── 시간 ────────────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Seoul")

# ── 학습량 ──────────────────────────────────────────────────────────────
NEW_PER_DAY = 2          # 아침에 새로 배울 표현 개수
MAX_REVIEWS_PER_DAY = 6  # 하루 복습 카드 상한 (밀려도 폭주하지 않게)
POOL_MIN = 20            # 풀이 이 아래로 떨어지면 ingest 가 표현을 보충한다

# ── 출처·풀 진입 기준 ───────────────────────────────────────────────────
# LLM 이 없으므로 "학습할 가치가 있는가"는 출처로 판단한다.
#  - MW Learner's 에 실려 있으면 통과 (학습자용 큐레이션 사전 = 흔한 표현이라는 근거)
#  - MW 에 없으면 Wiktionary 정의 + Tatoeba 예문이 이만큼은 있어야 통과
MIN_TATOEBA_FOR_WIKTIONARY = 2
EXAMPLES_PER_CARD = 3     # 가능하면 서로 다른 출처에서
MW_DAILY_LIMIT = 900      # 무료 키는 하루 1000 쿼리. 여유를 둔다.

# ── SRS (Leitner) ───────────────────────────────────────────────────────
# 박스 번호 -> 다음 복습까지의 일수. 마지막 박스를 통과하면 졸업(retired).
BOX_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}
MAX_BOX = max(BOX_INTERVALS)

# ── 발음 ────────────────────────────────────────────────────────────────
YOUGLISH_ACCENT = "us"   # us | uk | english | australian | canadian | irish
TTS_LANG = "en"
TTS_TLD = "com"          # gTTS 억양: com=미국, co.uk=영국
GAP_SECONDS = 0.7        # 예문 사이 무음 길이

# ── 한국어 ──────────────────────────────────────────────────────────────
# 기본 OFF. 텔레그램 /korean on|off 로 바꾸며 값은 state.json 에 저장된다.
KOREAN_DEFAULT = False
MT_LABEL = "(자동번역)"
