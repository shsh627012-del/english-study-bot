"""Wiktionary — 후보 표현 대량 수집 + MW 에 없는 표현의 영영 정의.

  python -m src.sources.wiktionary --harvest      카테고리 전량 수집 → candidates.json
  python -m src.sources.wiktionary "be swamped"   정의 조회 테스트

라이선스: CC BY-SA. 정의를 보여줄 때는 항상 원문 링크를 함께 붙인다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import time

from .http import BOT_UA, get_json

API = "https://en.wiktionary.org/w/api.php"
PAGE = "https://en.wiktionary.org/wiki/{title}"
SOURCE_NAME = "Wiktionary"

CATEGORIES = {
    "English idioms": "idiom",
    "English phrasal verbs": "phrasal_verb",
    "English proverbs": "proverb",
    "English similes": "simile",
}

PLACEHOLDERS = {"someone", "somebody", "something", "one's", "someone's", "sb", "sth"}
LIGHT_VERBS = {"be", "get", "go", "play", "have", "feel", "keep", "make"}

# 한국 교과서·시중 교재에 흔해서 굳이 알림으로 받을 필요 없는 것들.
TOO_FAMILIAR = {
    "piece of cake", "break a leg", "raining cats and dogs", "rain cats and dogs",
    "a piece of cake", "hit the books", "under the weather", "once in a blue moon",
    "better late than never", "time flies", "easy come, easy go", "no pain, no gain",
    "look forward to", "give up", "take care of", "get up", "wake up", "look for",
    "look after", "turn on", "turn off", "put on", "take off", "come back", "go out",
    "sit down", "stand up", "find out", "pick up", "grow up", "hang out",
}

POS_HEADERS = {"Verb": "phrasal_verb", "Phrase": "idiom", "Noun": "noun",
               "Adjective": "adjective", "Adverb": "adverb", "Prepositional phrase": "idiom",
               "Idiom": "idiom", "Proverb": "proverb", "Interjection": "idiom"}


# ── 후보 수집 ───────────────────────────────────────────────────────────
def _category_members(category: str):
    params = {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
              "cmnamespace": "0", "cmlimit": "500", "format": "json"}
    while True:
        data = get_json(API + "?" + urllib.parse.urlencode(params), ua=BOT_UA)
        for m in data.get("query", {}).get("categorymembers", []):
            yield m["title"]
        if "continue" not in data:
            break
        params.update(data["continue"])
        time.sleep(1.0)                      # Wikimedia API 예절: 순차 요청, 간격 두기


def is_useful(title: str) -> bool:
    """원본 카테고리는 지저분하다 (101, 11 Downing Street, ab off ...). 걸러낸다."""
    words = title.split()
    if not 2 <= len(words) <= 8:                  # 한 단어는 이디엄 학습 대상이 아님
        return False
    if not re.fullmatch(r"[A-Za-z' ,\-]+", title):  # 숫자·기호·비ASCII
        return False
    if any(w[0].isupper() for w in words):       # 고유명사·지명·인명
        return False
    if title.lower() in TOO_FAMILIAR:
        return False
    return True


def harvest(out_path: Path) -> dict:
    seen: dict[str, dict] = {}
    for category, pos in CATEGORIES.items():
        total = kept = 0
        for title in _category_members(category):
            total += 1
            if title.lower() in seen or not is_useful(title):
                continue
            seen[title.lower()] = {
                "text": title,
                "pos": pos,
                "wiktionary": PAGE.format(title=urllib.parse.quote(title.replace(" ", "_"))),
                "status": "new",
            }
            kept += 1
        print(f"  {category:24s} {total:>6,}개 중 {kept:>6,}개 채택")

    doc = {"harvested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "candidates": sorted(seen.values(), key=lambda c: c["text"])}
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n후보 {len(doc['candidates']):,}개 → {out_path}")
    return doc


# ── 정의 조회 ───────────────────────────────────────────────────────────
def _titles(phrase: str) -> list[str]:
    """조회할 문서 제목 후보. 자리표시어·앞 관사·가벼운 동사를 뺀 형태까지."""
    words = phrase.split()
    forms = [words, [w for w in words if w.lower() not in PLACEHOLDERS]]
    if words and words[0].lower() in ("a", "an", "the"):
        forms.append(words[1:])
    if words and words[0].lower() in LIGHT_VERBS:
        forms.append(words[1:])
    return list(dict.fromkeys(" ".join(f) for f in forms if f))


def _clean(wikitext: str) -> str:
    t = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^/]*/>", "", wikitext)
    t = re.sub(r"\{\{(?:lb|lbl|label)\|en\|[^}]*\}\}", "", t)        # 라벨은 따로 뽑는다
    # {{m|en|word}}, {{l|en|word}}, {{w|word}}, {{q|text}}, {{gloss|text}} → 마지막 인자
    t = re.sub(r"\{\{(?:m|l|w|q|qualifier|gloss|gl|term|ll)\|(?:[^{}|]*\|)*([^{}|=]+)\}\}", r"\1", t)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)                              # 나머지 템플릿 제거
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", t)          # [[a|b]] → b
    t = re.sub(r"'{2,}", "", t)                                       # '''굵게''' ''기울임''
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip(" ;:,")


def _labels(line: str) -> str | None:
    labels = []
    for m in re.finditer(r"\{\{(?:lb|lbl|label)\|en\|([^}]*)\}\}", line):
        labels += [x for x in m.group(1).split("|") if x and x not in ("_", "and", "or")]
    return ", ".join(labels) or None


def parse_entry(wikitext: str) -> dict | None:
    """영어 섹션에서 첫 번째 쓸 만한 정의와 그 예문들을 뽑는다."""
    m = re.search(r"^==\s*English\s*==\s*$", wikitext, re.M)
    if not m:
        return None
    section = wikitext[m.end():]
    nxt = re.search(r"^==[^=]", section, re.M)
    section = section[: nxt.start()] if nxt else section

    pos = None
    for line in section.splitlines():
        header = re.match(r"^=+\s*([^=]+?)\s*=+\s*$", line)
        if header:
            pos = POS_HEADERS.get(header.group(1))
            continue
        if not pos or not line.startswith("# "):
            continue
        # {{infl of|...}} 같은 '굴절형입니다' 정의는 건너뛴다.
        if re.match(r"#\s*\{\{(?:infl of|inflection of|past participle of|plural of|"
                    r"alternative form of|alt form|misspelling of)", line):
            continue
        definition = _clean(line[2:])
        if len(definition) < 8:
            continue
        return {"definition_en": definition, "label": _labels(line), "pos": pos,
                "examples": _examples_after(section, line)}
    return None


def _examples_after(section: str, def_line: str) -> list[str]:
    """정의 바로 아래 '#:' 줄의 {{ux|en|...}} 예문. 인용문(#*)은 쓰지 않는다."""
    lines = section.splitlines()
    i = lines.index(def_line) + 1
    out = []
    while i < len(lines) and lines[i].startswith("#") and not lines[i].startswith("# "):
        ux = re.match(r"#:\s*\{\{(?:ux|usex|eg)\|en\|(.+)\}\}\s*$", lines[i])
        if ux:
            body = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", ux.group(1))
            text = _clean(body.split("|")[0])      # 첫 인자가 예문, 나머지는 번역·주석
            if text:
                out.append(text)
        i += 1
    return out


def lookup(phrase: str) -> dict | None:
    """(MW 가 실패했을 때의) Wiktionary 영영 정의. 리다이렉트를 따라간다."""
    titles = _titles(phrase)
    params = {"action": "query", "titles": "|".join(titles), "redirects": "1",
              "prop": "revisions", "rvprop": "content", "rvslots": "main",
              "format": "json", "formatversion": "2"}
    data = get_json(API + "?" + urllib.parse.urlencode(params), ua=BOT_UA)
    pages = {p["title"]: p for p in data.get("query", {}).get("pages", []) if "revisions" in p}

    # 요청한 순서대로 (리다이렉트 결과 이름으로) 확인한다.
    redirects = {r["from"]: r["to"] for r in data.get("query", {}).get("redirects", [])}
    for title in titles:
        page = pages.get(redirects.get(title, title))
        if not page:
            continue
        entry = parse_entry(page["revisions"][0]["slots"]["main"]["content"])
        if entry:
            url = PAGE.format(title=urllib.parse.quote(page["title"].replace(" ", "_")))
            entry["matched"] = page["title"]
            entry["definition_source"] = {"name": SOURCE_NAME, "url": url}
            return entry
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Wiktionary 후보 수집 / 정의 조회")
    ap.add_argument("phrase", nargs="?")
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--out", default="docs/data/candidates.json")
    args = ap.parse_args()

    if args.harvest:
        harvest(Path(args.out))
        return 0
    if args.phrase:
        print(json.dumps(lookup(args.phrase), ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
