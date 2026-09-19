"""주간 리포트를 텔레그램으로 보낸다.

  python -m src.report            지난 7일
  python -m src.report --dry-run
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta

from . import config, srs, store
from .telegram import esc, send_message


def build(days: int = 7) -> str:
    since = (datetime.now(config.TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in store.read_log() if r.get("date", "") >= since]

    learned = [r for r in rows if r.get("event") == "sent" and r.get("kind") == "new"]
    graded = [r for r in rows if r.get("event") == "graded"]
    grades = Counter(r.get("grade") for r in graded)

    # 자주 헷갈린 표현
    trouble = Counter(
        r["text"] for r in graded if r.get("grade") in ("unknown", "vague")
    ).most_common(5)

    expressions = store.load_expressions()
    state = store.load_srs()
    dist = srs.box_distribution(state)
    active = sum(1 for e in expressions if e.get("status") == "active")
    retired = sum(1 for e in expressions if e.get("status") == "retired")
    pool = sum(1 for e in expressions if e.get("status") == "pool")

    answered = sum(grades[g] for g in ("know", "vague", "unknown"))
    know_rate = round(grades["know"] / answered * 100) if answered else 0

    lines = [
        f"<b>📅 주간 리포트</b>  <i>({since} ~ {store.today_kst()})</i>",
        "",
        f"새로 배운 표현  <b>{len(learned)}개</b>",
        f"응답한 카드      <b>{answered}개</b>  ·  아는 비율 <b>{know_rate}%</b>",
        "",
        f"😀 {grades['know']}   🤔 {grades['vague']}   😵 {grades['unknown']}   🙄 {grades['too_easy']}",
        "",
        f"<b>진도</b>  학습 중 {active} · 졸업 {retired} · 대기 {pool}",
    ]

    if dist:
        lines.append("")
        for box, n in dist.items():
            if box <= config.MAX_BOX:
                gap = config.BOX_INTERVALS[box]
                lines.append(f"  박스 {box} ({gap}일)  {'▮' * min(n, 18)} {n}")

    if trouble:
        lines += ["", "<b>🔁 자주 헷갈린 표현</b>"]
        lines += [f"  • {esc(t)} ({n}회)" for t, n in trouble]

    if learned:
        lines += ["", "<b>이번 주 표현</b>"]
        lines += [f"  • {esc(r['text'])}" for r in learned[-14:]]

    if grades["too_easy"]:
        lines += ["", f"<i>🙄 로 표시한 {grades['too_easy']}개는 다음 생성부터 제외됩니다.</i>"]

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="주간 리포트")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = build(args.days)
    if args.dry_run:
        import re
        print(re.sub(r"</?[a-z]+>", "", text))
    else:
        send_message(text)
        store.append_log("report", days=args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
