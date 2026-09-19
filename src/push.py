"""오늘의 표현을 텔레그램으로 보낸다.

  python -m src.push --morning          아침: 새 표현 + 복습 카드
  python -m src.push --evening          저녁: 빈칸 퀴즈 + 섀도잉
  python -m src.push --morning --dry-run   보내지 않고 화면에만 출력
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

from . import config, pronounce, srs, store, translate
from .sources.match import phrase_regex
from .telegram import TelegramError, esc, send_message, send_voice

POS_KO = {
    "phrasal_verb": "구동사",
    "idiom": "관용표현",
    "noun": "명사",
    "verb": "동사",
    "adjective": "형용사",
    "collocation": "연어",
}


# ── 카드 렌더링 ─────────────────────────────────────────────────────────
def _short_source(source: dict) -> str:
    """버튼·태그에 쓸 짧은 출처 이름."""
    name = source.get("name", "")
    for key, short in (("Merriam-Webster", "MW"), ("Wiktionary", "Wiktionary"),
                       ("Tatoeba", "Tatoeba"), ("YouTube", "YouTube")):
        if name.startswith(key):
            return short
    return name.split(" — ")[0] or "출처"


def _link(text: str, url: str | None) -> str:
    return f'<a href="{esc(url)}">{esc(text)}</a>' if url else esc(text)


def _ko_line(ko: str | None, origin: str | None) -> str | None:
    if not ko:
        return None
    tag = f" {config.MT_LABEL}" if origin == "machine" else ""
    return f"    <i>{esc(ko)}</i>{esc(tag)}"


def render_card(exp: dict, header: str, korean: bool = False) -> str:
    """영영 정의 우선. 모든 정의·예문에 원문 링크를 붙여 직접 검증할 수 있게 한다."""
    pron = exp.get("pronunciation", {})
    ipa = f"  <code>{esc(pron['ipa'])}</code>" if pron.get("ipa") else ""
    pos = POS_KO.get(exp.get("pos", ""), exp.get("pos", ""))
    label = exp.get("definition_label")
    dsrc = exp.get("definition_source", {})

    lines = [
        f"<b>{esc(header)}</b>" + (f"   ·   {esc(pos)}" if pos else ""),
        "",
        f"<b>{esc(exp['text'])}</b>{ipa}",
        (f"<i>[{esc(label)}]</i> " if label else "") + esc(exp["definition_en"]),
        f"    — {_link(dsrc.get('name', ''), dsrc.get('url'))}",
    ]
    if korean:
        ko = _ko_line(exp.get("meaning_ko"), exp.get("ko_origin"))
        if ko:
            lines.append(ko)
    lines.append("")

    for i, ex in enumerate(exp.get("examples", []), 1):
        src = ex.get("source", {})
        mic = " 🎙" if ex.get("audio") else ""       # 원어민 녹음이 있는 예문
        lines.append(f"{i}. {esc(ex['en'])}  [{_link(_short_source(src), src.get('url'))}]{mic}")

    if exp.get("source", {}).get("type") == "youtube" and exp["source"].get("title"):
        lines += ["", f"📺 {_link(exp['source']['title'], exp['source'].get('ref'))}"]
    return "\n".join(lines)


def naver_url(phrase: str) -> str:
    import urllib.parse
    return "https://en.dict.naver.com/#/search?query=" + urllib.parse.quote(phrase)


def card_keyboard(exp: dict) -> list[list[dict]]:
    pron = exp.get("pronunciation", {})
    rows: list[list[dict]] = []

    links = []
    if pron.get("youglish"):
        links.append({"text": "🔊 실제 발음", "url": pron["youglish"]})
    if pron.get("source_clip"):
        links.append({"text": "📺 원본 장면", "url": pron["source_clip"]})
    if pron.get("dict_audio"):
        word = pron.get("dict_word") or "단어"
        links.append({"text": f"🔤 {word}", "url": pron["dict_audio"]})
    if links:
        rows.append(links[:3])
    lookup = []
    if exp.get("definition_source", {}).get("url"):
        lookup.append({"text": "📖 사전 원문", "url": exp["definition_source"]["url"]})
    # 자연스러운 한국어 뜻은 네이버 사전에서 직접 확인한다 (자동 수집하지 않는다).
    lookup.append({"text": "🇰🇷 네이버 사전", "url": naver_url(exp["text"])})
    rows.append(lookup)

    eid = exp["id"]
    rows.append([
        {"text": srs.GRADE_LABEL["know"], "callback_data": f"g:{eid}:know"},
        {"text": srs.GRADE_LABEL["vague"], "callback_data": f"g:{eid}:vague"},
    ])
    rows.append([
        {"text": srs.GRADE_LABEL["unknown"], "callback_data": f"g:{eid}:unknown"},
        {"text": srs.GRADE_LABEL["too_easy"], "callback_data": f"g:{eid}:too_easy"},
    ])
    return rows


# ── 보내기 ──────────────────────────────────────────────────────────────
def _voice_path(exp: dict) -> Path | None:
    rel = exp.get("pronunciation", {}).get("tts_file")
    if rel:
        p = config.DOCS / rel
        # ffmpeg 없는 곳(로컬 Windows)에서 만든 mp3 는 합성음뿐이고 음성 메시지도 아니다.
        # ffmpeg 이 있으면 원어민 녹음을 섞은 ogg 로 다시 만든다.
        stale = p.suffix == ".mp3" and pronounce._have_ffmpeg()
        if p.exists() and not stale:
            return p
    return pronounce.build_voice(exp)


def _plain(html_text: str) -> str:
    """--dry-run 출력용. 링크는 '텍스트 <주소>' 로 풀어 보여준다."""
    import html as _html
    t = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2 <\1>", html_text)
    return _html.unescape(re.sub(r"</?(?:b|i|code)>", "", t))


def send_card(exp: dict, header: str, dry: bool, with_voice: bool = True,
              korean: bool = False) -> None:
    if korean:
        translate.fill_korean(exp)                 # 비어 있을 때만, 결과는 표현에 저장된다
    text = render_card(exp, header, korean=korean)
    keyboard = card_keyboard(exp)

    if dry:
        print("\n" + "=" * 60)
        print(_plain(text))
        print("-" * 60)
        for row in keyboard:
            print("  " + " | ".join(b["text"] for b in row))
        return

    send_message(text, keyboard)
    if with_voice:
        path = _voice_path(exp)
        if path:
            rel = path.relative_to(config.DOCS) if config.DOCS in path.parents else path.name
            exp.setdefault("pronunciation", {})["tts_file"] = str(rel).replace("\\", "/")
            try:
                send_voice(path, caption=f"🔊 <b>{esc(exp['text'])}</b> — 표현 + 예문")
            except TelegramError as e:
                print(f"  [경고] 음성 전송 실패 ({exp['id']}): {e}")


# ── 아침 ────────────────────────────────────────────────────────────────
def pick_new(expressions: list[dict], n: int) -> list[dict]:
    """웹에서 승격한(priority 높은) 표현을 먼저, 그다음 오래 대기한 순."""
    pool = [e for e in expressions if e.get("status") == "pool"]
    pool.sort(key=lambda e: (-e.get("priority", 0), e.get("created_at", "")))
    return pool[:n]


def run_morning(dry: bool) -> int:
    expressions = store.load_expressions()
    state = store.load_srs()

    new_items = pick_new(expressions, store.new_per_day())
    review_ids = [
        cid for cid in srs.due_cards(state)
        if (e := store.find_expression(expressions, cid)) and e.get("status") == "active"
    ][: config.MAX_REVIEWS_PER_DAY]

    if not new_items and not review_ids:
        print("보낼 표현이 없습니다. `python -m src.ingest` 로 풀을 채우세요.")
        return 1

    total = len(new_items)
    korean = store.korean_enabled()
    for i, exp in enumerate(new_items, 1):
        send_card(exp, f"🌱 오늘의 표현 {i}/{total}", dry, korean=korean)
        if not dry:
            exp["status"] = "active"
            srs.start_card(state, exp["id"])
            store.append_log("sent", mode="morning", kind="new", id=exp["id"], text=exp["text"])

    for i, cid in enumerate(review_ids, 1):
        exp = store.find_expression(expressions, cid)
        send_card(exp, f"🔁 복습 {i}/{len(review_ids)}", dry, with_voice=False, korean=korean)
        if not dry:
            state["cards"][cid]["sent_count"] += 1
            store.append_log("sent", mode="morning", kind="review", id=cid, text=exp["text"])

    if not dry:
        store.save_expressions(expressions)
        store.save_srs(state)
        store.append_log("push", mode="morning", new=len(new_items), review=len(review_ids))
    print(f"아침 발송 완료 — 새 표현 {len(new_items)}개, 복습 {len(review_ids)}개")
    return 0


# ── 저녁 ────────────────────────────────────────────────────────────────
def _today_expression_ids() -> list[str]:
    today = store.today_kst()
    return [
        r["id"] for r in store.read_log()
        if r.get("date") == today and r.get("event") == "sent" and r.get("kind") == "new"
    ]


def make_quiz(exp: dict, others: list[dict],
              korean: bool = False) -> tuple[str, list[list[dict]]] | None:
    """예문에서 표현을 가리고 4지선다. 힌트는 영영 정의."""
    pat = phrase_regex(exp["text"])
    # 표현이 실제로 들어 있는 예문만 퀴즈로 쓸 수 있다 (굴절형 포함).
    ex = next((e for e in exp.get("examples") or [] if pat.search(e["en"])), None)
    if not ex:
        return None
    blanked = pat.sub("_____", ex["en"], count=1)

    wrong = random.sample(others, k=min(3, len(others)))
    choices = [(exp["text"], True)] + [(w["text"], False) for w in wrong]
    random.shuffle(choices)

    lines = ["<b>🌙 오늘의 복습 퀴즈</b>", "", esc(blanked), "",
             f"💡 <i>{esc(exp['definition_en'])}</i>"]
    if korean:
        ko = _ko_line(exp.get("meaning_ko"), exp.get("ko_origin"))
        if ko:
            lines.append(ko)
    lines += ["", "빈칸에 들어갈 표현은?"]
    keyboard = [
        [{"text": t, "callback_data": f"q:{exp['id']}:{'c' if ok else 'w'}"}]
        for t, ok in choices
    ]
    return "\n".join(lines), keyboard


def run_evening(dry: bool) -> int:
    expressions = store.load_expressions()
    ids = _today_expression_ids()
    todays = [e for e in (store.find_expression(expressions, i) for i in ids) if e]

    if not todays:
        print("오늘 새로 배운 표현이 없어 퀴즈를 건너뜁니다.")
        return 0

    others = [e for e in expressions if e["id"] not in ids]
    for exp in todays:
        korean = store.korean_enabled()
        if korean and not dry:
            translate.fill_korean(exp)             # 아침에 한국어가 꺼져 있었으면 여기서 채운다
        quiz = make_quiz(exp, others, korean=korean)
        if not quiz:
            continue
        text, keyboard = quiz
        if dry:
            print("\n" + "=" * 60)
            print(_plain(text))
            for row in keyboard:
                print("  " + row[0]["text"])
        else:
            send_message(text, keyboard)
            store.append_log("quiz", mode="evening", id=exp["id"])

    # 섀도잉: 오늘 표현 중 하나를 음성으로 다시 듣고 따라 말하기
    target = todays[0]
    if dry:
        print(f"\n[섀도잉] {target['text']} 음성 재전송")
    else:
        path = _voice_path(target)
        if path:
            target["pronunciation"]["tts_file"] = f"audio/{path.name}"
            try:
                send_voice(path, caption=(
                    "🗣 <b>섀도잉</b> — 듣고 그대로 따라 말해보세요.\n"
                    "(재생 속도를 1.5×로 올리면 더 어렵습니다)"
                ))
            except TelegramError as e:
                print(f"  [경고] 섀도잉 음성 전송 실패: {e}")

    if not dry:
        store.save_expressions(expressions)       # 번역·음성 경로를 저장해 다음엔 재사용
        store.append_log("push", mode="evening", count=len(todays))
    print(f"저녁 발송 완료 — 퀴즈 {len(todays)}개")
    return 0


# ── 진입점 ──────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="오늘의 영어 표현 발송")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--morning", action="store_true", help="새 표현 + 복습")
    group.add_argument("--evening", action="store_true", help="빈칸 퀴즈 + 섀도잉")
    ap.add_argument("--dry-run", action="store_true", help="보내지 않고 출력만")
    ap.add_argument("--force", action="store_true", help="오늘 이미 보냈어도 다시 보냄")
    args = ap.parse_args()

    mode = "morning" if args.morning else "evening"
    if not args.dry_run and not args.force and store.already_ran("push", mode):
        print(f"오늘 {mode} 발송이 이미 끝났습니다. 다시 보내려면 --force.")
        return 0

    return run_morning(args.dry_run) if args.morning else run_evening(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
