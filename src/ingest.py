"""표현 풀을 보충한다 — LLM 없이, 사람이 편집한 출처만으로 카드를 조립한다.

  python -m src.ingest              풀이 부족하면 Wiktionary 후보에서 보충
  python -m src.ingest --news       영어 뉴스에서 실제 쓰인 예문도 붙임
  python -m src.ingest --force -n 6 부족하지 않아도 6개 보충

조립 규칙
  정의  : Merriam-Webster Learner's → 없으면 Wiktionary
  예문  : 사전 예문 + Tatoeba (+ 뉴스·유튜브) — 가능하면 서로 다른 출처에서
  통과  : MW 에 실려 있거나, Wiktionary 정의 + Tatoeba 예문이 충분할 것
          (학습자용 사전에 실렸다는 것 자체가 흔히 쓰이는 표현이라는 근거다)
모든 정의·예문에는 출처 링크가 붙는다.
"""
from __future__ import annotations

import argparse
import random
import sys

from . import config, pronounce, store
from .sources import dictionary, tatoeba, wiktionary


def _example(en: str, source: dict, audio: dict | None = None,
             ko: str | None = None, ko_origin: str | None = None) -> dict:
    return {"en": en, "ko": ko, "ko_origin": ko_origin, "source": source, "audio": audio}


def pick_examples(dict_examples: list[dict], corpus_examples: list[dict],
                  n: int = config.EXAMPLES_PER_CARD) -> list[dict]:
    """사전 예문과 코퍼스 예문을 번갈아 뽑아 출처가 겹치지 않게 한다."""
    out: list[dict] = []
    seen: set[str] = set()
    queues = [list(dict_examples), list(corpus_examples)]
    while len(out) < n and any(queues):
        for q in queues:
            while q:
                ex = q.pop(0)
                key = ex["en"].lower().rstrip(".!?")
                if key not in seen:
                    seen.add(key)
                    out.append(ex)
                    break
            if len(out) >= n:
                break
    return out


def assemble(text: str, pos: str | None = None, origin: dict | None = None,
             items: list[dict] | None = None) -> tuple[dict | None, str | None]:
    """출처에서 카드 하나를 조립한다. (카드, None) 또는 (None, 탈락 사유)."""
    mw = None
    if store.mw_budget_left() > 0:
        mw, used = dictionary.lookup(text, key=config.MERRIAM_WEBSTER_KEY)
        store.spend_mw(used)

    wk = None if mw else wiktionary.lookup(text)
    if not mw and not wk:
        return None, "정의 없음 (MW·Wiktionary 모두)"

    corpus = tatoeba.examples(text, limit=4)
    if not mw and len(corpus) < config.MIN_TATOEBA_FOR_WIKTIONARY:
        return None, f"학습자 사전에 없고 실사용 예문도 부족 (Tatoeba {len(corpus)}건)"

    definition = mw or wk
    dict_examples = [_example(e, definition["definition_source"]) for e in definition["examples"]]
    examples = pick_examples(dict_examples, corpus)
    if not examples:
        return None, "예문 없음"

    ipa, dict_audio, dict_word = pronounce.dictionary_lookup(text)
    record = {
        "id": store.next_expression_id(items if items is not None else store.load_expressions()),
        "text": text,
        "pos": pos or (wk or {}).get("pos") or "idiom",
        "definition_en": definition["definition_en"],
        "definition_label": definition.get("label"),
        "definition_source": definition["definition_source"],
        "meaning_ko": None,
        "ko_origin": None,
        "examples": examples,
        "pronunciation": {
            "ipa": ipa,
            "youglish": pronounce.youglish_url(text),
            "dict_audio": dict_audio,
            "dict_word": dict_word,
            "mw_audio": mw.get("audio") if mw else None,
            "mw_audio_word": mw.get("audio_word") if mw else None,
            "tts_file": None,
            "source_clip": None,
        },
        "source": origin or {"type": "wiktionary",
                             "ref": wiktionary.PAGE.format(title=text.replace(" ", "_"))},
        "created_at": store.now_iso(),
        "status": "pool",
        "priority": 0,
    }
    return record, None


def run(count: int, use_news: bool, force: bool) -> int:
    items = store.load_expressions()
    pool = [e for e in items if e.get("status") == "pool"]
    if not force and len(pool) >= config.POOL_MIN:
        print(f"풀에 {len(pool)}개 남아 있어 보충하지 않습니다 (기준 {config.POOL_MIN}개).")
        return 0

    need = count or max(config.POOL_MIN - len(pool), config.NEW_PER_DAY * 4)
    status = store.load_candidate_status()
    taken = {e["text"].lower() for e in items} | {k.lower() for k in store.load_known()}
    candidates = [c for c in store.load_candidates()
                  if c["text"].lower() not in status and c["text"].lower() not in taken]
    if not candidates:
        print("남은 후보가 없습니다. `python -m src.sources.wiktionary --harvest` 로 다시 수집하세요.")
        return 1
    random.shuffle(candidates)

    print(f"보충 목표 {need}개 · 남은 후보 {len(candidates):,}개 · 오늘 MW 잔여 {store.mw_budget_left()}회\n")
    added: list[dict] = []
    tried = 0
    for c in candidates:
        if len(added) >= need:
            break
        if store.mw_budget_left() <= 4:
            print("\n오늘 Merriam-Webster 쿼리 한도에 가까워 멈춥니다.")
            break
        tried += 1
        try:
            record, reason = assemble(c["text"], c.get("pos"), items=items + added)
        except Exception as e:                    # 출처 하나가 죽어도 나머지는 계속
            print(f"  ! {c['text']} — 조회 오류: {e}")
            continue
        if record:
            added.append(record)
            status[c["text"].lower()] = "used"
            src = record["definition_source"]["name"]
            print(f"  ✓ {record['text']:36s} [{src}] 예문 {len(record['examples'])}")
        else:
            status[c["text"].lower()] = f"rejected: {reason}"
            print(f"  ✗ {c['text']:36s} {reason}")

    if use_news and added:
        from .sources.news_rss import attach_news_examples
        attached = attach_news_examples(items + added)
        print(f"\n  📰 뉴스 원문 예문 {attached}건 추가")

    store.save_candidate_status(status)
    if not added:
        print("\n추가된 표현이 없습니다.")
        return 1
    items.extend(added)
    store.save_expressions(items)
    store.append_log("ingested", source="dictionary", count=len(added), tried=tried)
    print(f"\n{tried}개 시도 → {len(added)}개 추가 (전체 {len(items)}개)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="표현 풀 보충 (사전·코퍼스 기반)")
    ap.add_argument("-n", "--count", type=int, default=0, help="보충 개수 (0=자동)")
    ap.add_argument("--news", action="store_true", help="영어 뉴스에서 실제 예문도 붙임")
    ap.add_argument("--force", action="store_true", help="풀이 충분해도 실행")
    args = ap.parse_args()
    return run(args.count, args.news, args.force)


if __name__ == "__main__":
    sys.exit(main())
