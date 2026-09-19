"""Leitner 박스 간격반복.

박스가 높을수록 다음 복습까지 멀어진다. 마지막 박스를 통과하면 졸업(retired).
모르는 표현은 박스 1로 떨어져 내일 다시 나온다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config, store

GRADES = ("know", "vague", "unknown", "too_easy")

GRADE_LABEL = {
    "know": "😀 알아요",
    "vague": "🤔 헷갈려요",
    "unknown": "😵 몰라요",
    "too_easy": "🙄 너무 쉬움",
}


def _today() -> date:
    return datetime.now(config.TZ).date()


def _due_after(box: int) -> str:
    return (_today() + timedelta(days=config.BOX_INTERVALS[box])).isoformat()


def start_card(srs: dict, exp_id: str) -> dict:
    """처음 발송한 표현을 박스 1로 등록한다."""
    card = srs["cards"].setdefault(exp_id, {
        "box": 1,
        "due": _due_after(1),
        "history": [],
        "sent_count": 0,
    })
    card["sent_count"] += 1
    return card


def due_cards(srs: dict, on: date | None = None) -> list[str]:
    """오늘(또는 지정일) 복습해야 하는 표현 ID. 오래 밀린 것부터."""
    today = (on or _today()).isoformat()
    due = [(cid, c) for cid, c in srs["cards"].items() if c.get("due", "") <= today]
    due.sort(key=lambda kv: kv[1].get("due", ""))
    return [cid for cid, _ in due]


def grade(srs: dict, exp_id: str, g: str) -> tuple[dict, bool]:
    """응답을 반영한다. (갱신된 카드, 졸업했는지) 를 돌려준다.

    know     → 박스 +1 (마지막 박스를 넘으면 졸업)
    vague    → 박스 유지, 내일 다시
    unknown  → 박스 1로 리셋
    too_easy → 즉시 졸업 + known 목록에 적립
    """
    if g not in GRADES:
        raise ValueError(f"알 수 없는 응답: {g}")

    card = srs["cards"].setdefault(exp_id, {
        "box": 1, "due": _due_after(1), "history": [], "sent_count": 1,
    })
    card["history"].append({"at": store.now_iso(), "grade": g})

    if g == "too_easy":
        card["box"] = config.MAX_BOX + 1
        card["due"] = "9999-12-31"
        return card, True

    if g == "know":
        card["box"] += 1
        if card["box"] > config.MAX_BOX:
            card["due"] = "9999-12-31"
            return card, True
    elif g == "unknown":
        card["box"] = 1
    # vague 는 박스를 그대로 두고 내일 다시 본다.

    card["due"] = _due_after(card["box"]) if g != "vague" else (
        (_today() + timedelta(days=1)).isoformat()
    )
    return card, False


def box_distribution(srs: dict) -> dict[int, int]:
    dist: dict[int, int] = {}
    for c in srs["cards"].values():
        dist[c["box"]] = dist.get(c["box"], 0) + 1
    return dict(sorted(dist.items()))
