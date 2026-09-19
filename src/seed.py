"""초기 표현 풀을 만든다. 정의·예문은 전부 사전·코퍼스에서 조립한다.

  python -m src.seed              발음 음성까지 생성
  python -m src.seed --no-audio   음성은 건너뛰고 링크·정의·예문만
  python -m src.seed --reset      기존 표현을 지우고 다시 만든다
"""
from __future__ import annotations

import argparse
import sys

from . import config, ingest, pronounce, store
from .seed_data import SEED


def build(with_audio: bool = True, reset: bool = False) -> int:
    items = [] if reset else store.load_expressions()
    have = {e["text"].lower() for e in items}
    status = store.load_candidate_status()
    added = 0

    for text, pos in SEED:
        if text.lower() in have:
            continue
        record, reason = ingest.assemble(text, pos, origin={"type": "seed", "ref": None},
                                         items=items)
        if not record:
            print(f"  ✗ {text:34s} {reason}")
            continue
        if with_audio:
            path = pronounce.build_voice(record)
            if path:
                record["pronunciation"]["tts_file"] = f"audio/{path.name}"
        items.append(record)
        status[text.lower()] = "used"
        added += 1
        srcs = sorted({ex["source"]["name"].split(" #")[0] for ex in record["examples"]})
        print(f"  ✓ {record['id']} {text:34s} [{record['definition_source']['name']}] "
              f"예문 {len(record['examples'])} ({', '.join(srcs)})")

    store.save_expressions(items)
    store.save_candidate_status(status)
    store.append_log("ingested", source="seed", count=added)
    print(f"\n표현 {added}개 추가 (전체 {len(items)}개) → {config.EXPRESSIONS_FILE}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="초기 표현 풀 생성")
    ap.add_argument("--no-audio", action="store_true", help="음성 생성 건너뛰기")
    ap.add_argument("--reset", action="store_true", help="기존 표현을 지우고 다시 만들기")
    args = ap.parse_args()
    return build(with_audio=not args.no_audio, reset=args.reset)


if __name__ == "__main__":
    sys.exit(main())
