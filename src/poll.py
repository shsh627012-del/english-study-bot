"""텔레그램에서 온 것들을 수거한다 (webhook 없이 getUpdates 폴링).

  - 버튼 응답(callback_query) → SRS 갱신
  - 유튜브/기사 링크         → inbox 대기열 적립
  - /korean on|off          → 한국어 표시 토글 (state.json)

  python -m src.poll
"""
from __future__ import annotations

import re
import sys

from . import config, srs, store, telegram
from .telegram import esc

URL_RE = re.compile(r"https?://\S+")
YOUTUBE_RE = re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", re.I)


def _done_keyboard(label: str) -> list[list[dict]]:
    return [[{"text": f"✅ {label}", "callback_data": "noop"}]]


# ── 버튼 응답 ───────────────────────────────────────────────────────────
def handle_callback(cb: dict, expressions: list[dict], state: dict,
                    answered: set[str]) -> None:
    data = cb.get("data", "")
    msg = cb.get("message") or {}

    if data == "noop":
        telegram.answer_callback_query(cb["id"])
        return

    # 버튼이 ✅ 로 바뀌기까지 최대 20분 걸려서 같은 카드를 여러 번 누를 수 있다.
    # 카드(메시지)당 첫 응답만 반영한다.
    # 대화방은 하나뿐이라 message_id 만으로 충분하다 (퍼블릭 리포에 chat_id 를 남기지 않는다).
    key = str(msg.get("message_id"))
    if msg.get("message_id"):
        if key in answered:
            return
        answered.add(key)

    kind, _, rest = data.partition(":")
    exp_id, _, value = rest.partition(":")
    exp = store.find_expression(expressions, exp_id)
    if not exp:
        telegram.answer_callback_query(cb["id"], "표현을 찾을 수 없습니다")
        return

    if kind == "g":                                   # 이해도 응답
        card, graduated = srs.grade(state, exp_id, value)
        if value == "too_easy":
            store.add_known(exp["text"])
            exp["status"] = "retired"
            note = "너무 쉬움 — 앞으로 이런 수준은 덜 나옵니다"
        elif graduated:
            exp["status"] = "retired"
            note = "졸업! 더 이상 나오지 않습니다"
        else:
            note = f"기록했어요 · 다음 복습 {card['due']}"
        label = srs.GRADE_LABEL[value]

    elif kind == "q":                                 # 저녁 퀴즈
        correct = value == "c"
        card, graduated = srs.grade(state, exp_id, "know" if correct else "unknown")
        if graduated:
            exp["status"] = "retired"
        note = "정답!" if correct else f"오답 — 정답은 “{exp['text']}”"
        label = "정답" if correct else "오답"

    else:
        telegram.answer_callback_query(cb["id"])
        return

    store.append_log("graded", id=exp_id, text=exp["text"], grade=value, kind=kind)
    telegram.answer_callback_query(cb["id"], note)
    if msg.get("message_id"):
        telegram.edit_reply_markup(msg["chat"]["id"], msg["message_id"],
                                   _done_keyboard(f"{label} · {note}"[:60]))


# ── 메시지 ──────────────────────────────────────────────────────────────
def handle_message(msg: dict) -> None:
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/"):
        handle_command(text)
        return

    urls = URL_RE.findall(text)
    if urls:
        added, dup = [], []
        for url in urls:
            (added if store.add_inbox(url, "telegram") else dup).append(url)
        lines = []
        if added:
            kinds = ["📺 유튜브" if YOUTUBE_RE.search(u) else "📰 링크" for u in added]
            lines.append(f"{', '.join(kinds)} {len(added)}건을 대기열에 담았어요.")
            lines.append("<i>PC에서 `python -m src.sources.youtube` 를 돌리면 표현을 뽑아냅니다.</i>")
        if dup:
            lines.append(f"이미 담겨 있던 링크 {len(dup)}건은 건너뜁니다.")
        telegram.send_message("\n".join(lines))
        return

    telegram.send_message(
        "무엇을 도와드릴까요?\n\n"
        "• 유튜브·기사 링크를 보내면 <b>표현 추출 대기열</b>에 담아요\n"
        "• /korean on · off   한국어 뜻 표시\n"
        "• /stats 진도   /due 오늘 복습   /help 도움말"
    )


# ── 명령어 ──────────────────────────────────────────────────────────────
def handle_command(text: str) -> None:
    cmd = text.split()[0].lower().lstrip("/").split("@")[0]

    if cmd in ("start", "help"):
        telegram.send_message(
            "<b>영어공부 봇</b>\n\n"
            "매일 아침 새 표현을, 저녁엔 복습 퀴즈를 보냅니다.\n"
            "정의와 예문은 전부 사전·코퍼스 원문이고, 출처 링크를 눌러 직접 확인할 수 있어요.\n\n"
            "• 유튜브·기사 링크를 보내면 <b>표현 추출 대기열</b>에 적립\n\n"
            "/korean on · off   한국어 뜻 표시 (기본 꺼짐, 켜면 기계번역에 (자동번역) 표시)\n"
            "/stats 진도   /due 오늘 복습   /pool 남은 표현"
        )
        return

    if cmd == "korean":
        arg = (text.split()[1:] or [""])[0].lower()
        state_file = store.load_state()
        if arg in ("on", "off"):
            state_file["korean"] = arg == "on"
            store.save_state(state_file)
        on = bool(state_file.get("korean", config.KOREAN_DEFAULT))
        telegram.send_message(
            f"한국어 표시: <b>{'켜짐' if on else '꺼짐'}</b>\n\n"
            + ("다음 카드부터 한국어 뜻이 붙습니다. 사람 번역이 없으면 기계번역이며 "
               f"<i>{config.MT_LABEL}</i> 로 표시됩니다.\n"
               "⚠️ 기계번역은 이디엄을 직역하는 경우가 많습니다 (예: cut corners → 모서리를 자르다). "
               "영영 정의를 기준으로 보세요."
               if on else "영영 정의만 표시합니다. 켜려면 /korean on")
        )
        return

    state = store.load_srs()
    expressions = store.load_expressions()

    if cmd == "stats":
        dist = srs.box_distribution(state)
        active = sum(1 for e in expressions if e.get("status") == "active")
        retired = sum(1 for e in expressions if e.get("status") == "retired")
        rows = "\n".join(
            f"  박스 {b}: {'▮' * min(n, 20)} {n}"
            for b, n in dist.items() if b <= config.MAX_BOX
        )
        telegram.send_message(
            f"<b>📊 진도</b>\n\n학습 중 {active}개 · 졸업 {retired}개\n\n{rows or '  아직 없음'}"
        )

    elif cmd == "due":
        ids = srs.due_cards(state)
        names = [e["text"] for i in ids if (e := store.find_expression(expressions, i))]
        telegram.send_message(
            f"<b>🔁 오늘 복습 {len(names)}개</b>\n\n"
            + ("\n".join(f"• {esc(n)}" for n in names[:20]) or "없습니다")
        )

    elif cmd == "pool":
        pool = [e for e in expressions if e.get("status") == "pool"]
        telegram.send_message(
            f"<b>🗂 대기 중인 표현 {len(pool)}개</b>\n\n"
            + ("\n".join(f"• {esc(e['text'])}" for e in pool[:20]) or "비어 있습니다")
        )

    else:
        telegram.send_message("모르는 명령이에요. /help 를 눌러보세요.")


# ── 진입점 ──────────────────────────────────────────────────────────────
def main() -> int:
    state_file = store.load_state()
    offset = state_file.get("telegram_offset", 0)

    updates = telegram.get_updates(offset)
    if not updates:
        print("새 업데이트 없음")
        return 0

    expressions = store.load_expressions()
    srs_state = store.load_srs()
    answered = set(state_file.get("answered", []))
    handled = 0

    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        try:
            if "callback_query" in u:
                handle_callback(u["callback_query"], expressions, srs_state, answered)
            elif "message" in u:
                handle_message(u["message"])
            handled += 1
        except Exception as e:                        # 하나가 실패해도 나머지는 처리한다
            print(f"  [경고] 업데이트 {u['update_id']} 처리 실패: {e}")

    store.save_expressions(expressions)
    store.save_srs(srs_state)
    # 루프 중 /korean 이 state 를 바꿨을 수 있으니 다시 읽고 필요한 값만 갱신한다.
    state_file = store.load_state()
    state_file["telegram_offset"] = offset
    state_file["answered"] = sorted(answered, key=int)[-500:]
    store.save_state(state_file)
    print(f"업데이트 {handled}건 처리 (다음 offset={offset})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
