"""docs/data/*.json 읽기·쓰기. 모든 상태가 여기를 통한다."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


# ── 기본 입출력 ─────────────────────────────────────────────────────────
def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text) if text else default


def _write(path: Path, data: Any) -> None:
    """같은 디렉터리에 임시 파일을 쓰고 교체한다. 중간에 죽어도 파일이 깨지지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_kst() -> str:
    return datetime.now(config.TZ).strftime("%Y-%m-%d")


# ── expressions ─────────────────────────────────────────────────────────
def load_expressions() -> list[dict]:
    return _read(config.EXPRESSIONS_FILE, {"expressions": []})["expressions"]


def save_expressions(items: list[dict]) -> None:
    _write(config.EXPRESSIONS_FILE, {"expressions": items})


def next_expression_id(items: list[dict]) -> str:
    used = [int(e["id"].split("_")[1]) for e in items if e.get("id", "").startswith("exp_")]
    return f"exp_{max(used, default=0) + 1:04d}"


def find_expression(items: list[dict], exp_id: str) -> dict | None:
    return next((e for e in items if e["id"] == exp_id), None)


# ── srs ─────────────────────────────────────────────────────────────────
def load_srs() -> dict:
    return _read(config.SRS_FILE, {"cards": {}})


def save_srs(srs: dict) -> None:
    _write(config.SRS_FILE, srs)


# ── known (너무 쉬움 목록) ──────────────────────────────────────────────
def load_known() -> list[str]:
    return _read(config.KNOWN_FILE, {"known": []})["known"]


def save_known(known: list[str]) -> None:
    _write(config.KNOWN_FILE, {"known": known})


def add_known(text: str) -> None:
    known = load_known()
    if text not in known:
        known.append(text)
        save_known(known)


# ── inbox (링크 대기열) ─────────────────────────────────────────────────
def load_inbox() -> list[dict]:
    return _read(config.INBOX_FILE, {"items": []})["items"]


def save_inbox(items: list[dict]) -> None:
    _write(config.INBOX_FILE, {"items": items})


def add_inbox(url: str, added_by: str) -> dict | None:
    """이미 있는 URL이면 None을 돌려준다(중복 투입 방지)."""
    items = load_inbox()
    if any(i["url"] == url for i in items):
        return None
    item = {
        "id": f"in_{len(items) + 1:04d}",
        "url": url,
        "added_by": added_by,
        "added_at": now_iso(),
        "status": "pending",
        "extracted": [],
        "error": None,
    }
    items.append(item)
    save_inbox(items)
    return item


# ── candidates (Wiktionary 수집 후보) ──────────────────────────────────
def load_candidates() -> list[dict]:
    return _read(config.CANDIDATES_FILE, {"candidates": []})["candidates"]


def load_candidate_status() -> dict[str, str]:
    """{표현(소문자): "used" | "rejected: 사유"}"""
    return _read(config.CANDIDATE_STATUS_FILE, {"status": {}})["status"]


def save_candidate_status(status: dict[str, str]) -> None:
    _write(config.CANDIDATE_STATUS_FILE, {"status": status})


# ── state (텔레그램 offset 등) ──────────────────────────────────────────
def load_state() -> dict:
    return _read(config.STATE_FILE, {"telegram_offset": 0})


def save_state(state: dict) -> None:
    _write(config.STATE_FILE, state)


def korean_enabled() -> bool:
    return bool(load_state().get("korean", config.KOREAN_DEFAULT))


def new_per_day() -> int:
    """하루 새 표현 개수. 텔레그램 /count 로 바꾼다."""
    n = load_state().get("new_per_day", config.NEW_PER_DAY)
    return n if n in config.NEW_PER_DAY_CHOICES else config.NEW_PER_DAY


def mw_budget_left() -> int:
    """오늘 남은 Merriam-Webster 쿼리 수 (무료 키: 하루 1000)."""
    used = load_state().get("mw_queries", {})
    count = used.get("count", 0) if used.get("date") == today_kst() else 0
    return max(0, config.MW_DAILY_LIMIT - count)


def spend_mw(n: int) -> None:
    state = load_state()
    used = state.get("mw_queries", {})
    if used.get("date") != today_kst():
        used = {"date": today_kst(), "count": 0}
    used["count"] += n
    state["mw_queries"] = used
    save_state(state)


# ── log ─────────────────────────────────────────────────────────────────
def append_log(event: str, **fields: Any) -> None:
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now_iso(), "date": today_kst(), "event": event, **fields}
    with config.LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log() -> list[dict]:
    if not config.LOG_FILE.exists():
        return []
    with config.LOG_FILE.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def already_ran(event: str, mode: str) -> bool:
    """cron 지연으로 같은 워크플로우가 두 번 도는 것을 막는다."""
    today = today_kst()
    return any(
        r.get("event") == event and r.get("mode") == mode and r.get("date") == today
        for r in read_log()
    )
