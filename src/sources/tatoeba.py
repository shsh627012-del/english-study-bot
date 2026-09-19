"""Tatoeba — 사람이 쓰고 검수한 영어 예문 + 원어민이 직접 녹음한 문장 음성.

영-한 번역쌍은 이디엄에 사실상 없다(실측: 5개 중 1개). 한국어는 덤으로만 쓴다.
라이선스: 문장 CC BY 2.0 FR. 보여줄 때 문장 링크와 녹음자를 함께 표기한다.

  python -m src.sources.tatoeba "cut corners"
"""
from __future__ import annotations

import json
import sys
import urllib.parse

from .http import get_json

API = "https://tatoeba.org/en/api_v0/search?{query}"
SENTENCE = "https://tatoeba.org/en/sentences/show/{id}"
AUDIO = "https://tatoeba.org/audio/download/{id}"
SOURCE_NAME = "Tatoeba"

PLACEHOLDERS = {"someone", "somebody", "something", "one's", "someone's", "sb", "sth"}
LIGHT_VERBS = {"be", "get", "go", "play", "have", "feel", "keep", "make"}


def _queries(phrase: str) -> list[str]:
    """정확한 구문 검색부터, 안 되면 자리표시어·앞 동사를 뺀 핵심부로."""
    words = phrase.split()
    core = [w for w in words if w.lower() not in PLACEHOLDERS]
    # 핵심부가 너무 짧으면 엉뚱한 뜻이 걸린다:
    # "run something by someone" → "run by" → "The cafe is run by students." (운영되다)
    forms = [words] + ([core] if len(core) >= 3 else [])
    if core and core[0].lower() in LIGHT_VERBS and len(core) > 2:
        forms.append(core[1:])
    if core and core[0].lower() in ("a", "an", "the"):
        forms.append(core[1:])
    return list(dict.fromkeys(f'"{" ".join(f)}"' for f in forms if len(f) >= 3 or f is words))


def _search(query: str, want_ko: bool) -> list[dict]:
    params = {"from": "eng", "query": query, "sort": "relevance"}
    if want_ko:
        params["to"] = "kor"
    return get_json(API.format(query=urllib.parse.urlencode(params))).get("results", [])


def _korean(result: dict) -> str | None:
    for group in result.get("translations") or []:
        for t in group:
            if t.get("lang") == "kor":
                return t.get("text")
    return None


def examples(phrase: str, limit: int = 3, want_ko: bool = False) -> list[dict]:
    """[{en, ko, ko_origin, source:{name,url}, audio:{url,author}|None}]

    오류 표시된 문장(correctness < 0)은 빼고, 녹음이 있는 문장을 앞에 둔다.
    """
    seen: set[str] = set()
    picked: list[dict] = []
    for q in _queries(phrase):
        for r in _search(q, want_ko=False):
            text = (r.get("text") or "").strip()
            if (r.get("correctness") or 0) < 0 or text in seen or not 15 <= len(text) <= 160:
                continue
            seen.add(text)
            audio = next((a for a in r.get("audios") or []), None)
            picked.append({
                "en": text,
                "ko": _korean(r) if want_ko else None,
                "ko_origin": "tatoeba" if want_ko and _korean(r) else None,
                "source": {"name": f"{SOURCE_NAME} #{r['id']}",
                           "url": SENTENCE.format(id=r["id"])},
                "audio": {"url": AUDIO.format(id=audio["id"]),
                          "author": audio.get("author")} if audio else None,
            })
        if len(picked) >= limit * 3:
            break

    # 녹음 있는 문장 우선, 그다음 짧은 순 (알림으로 읽기 편하게)
    picked.sort(key=lambda x: (x["audio"] is None, len(x["en"])))

    # 한국어가 필요하면 사람 번역이 달린 문장을 따로 찾아 앞에 끼운다.
    if want_ko:
        for q in _queries(phrase)[:1]:
            for r in _search(q, want_ko=True):
                ko = _korean(r)
                match = next((p for p in picked if p["en"] == r.get("text")), None)
                if ko and match:
                    match["ko"], match["ko_origin"] = ko, "tatoeba"
    return picked[:limit]


if __name__ == "__main__":
    phrase = " ".join(sys.argv[1:]) or "cut corners"
    print(json.dumps(examples(phrase, want_ko=True), ensure_ascii=False, indent=2))
