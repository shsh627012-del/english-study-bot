"""Merriam-Webster Learner's Dictionary 에서 영영 정의·예문·발음을 가져온다.

무료 키 조건: 비상업적 사용, 키당 하루 1000 쿼리, MW 로고 표시 의무.

이디엄·구동사는 대개 최상위 표제어가 아니라 기반 단어 항목 안의
run-on(`dros`)으로 중첩돼 있다. 예) cut corners → corner 항목의 dros.
그래서 ① 구문 그대로 조회 → ② 내용어별로 조회해 dros 안에서 찾는 2단계로 간다.
"""
from __future__ import annotations

import os
import re
import urllib.parse

API = "https://dictionaryapi.com/api/v3/references/learners/json/{q}?key={key}"
PAGE = "https://www.learnersdictionary.com/definition/{word}"
AUDIO = "https://media.merriam-webster.com/audio/prons/en/us/mp3/{sub}/{name}.mp3"
SOURCE_NAME = "Merriam-Webster Learner's"

# 매칭할 때 양쪽에서 지우는 자리표시어. "throw someone under the bus" 와
# MW 의 "throw (someone) under the bus" 를 같은 것으로 본다.
PLACEHOLDERS = {"someone", "somebody", "something", "someone's", "somebody's",
                "one's", "sb", "sth", "it", "my", "your", "our", "their", "his", "her"}
# MW 는 과거분사형으로 싣기도 한다 (blown out of proportion).
IRREGULAR = {"blown": "blow", "thrown": "throw", "gone": "go", "taken": "take",
             "gotten": "get", "got": "get", "given": "give", "known": "know",
             "shaken": "shake", "broken": "break", "driven": "drive"}
# 학습자가 흔히 앞에 붙여 외우는 가벼운 동사. MW 표제어는 이게 없는 경우가 많다
# (get cold feet → cold feet, play devil's advocate → devil's advocate).
LIGHT_VERBS = {"be", "get", "go", "play", "have", "feel", "keep", "make"}
STOPWORDS = {"a", "an", "the", "be", "to", "of", "in", "on", "at", "by", "for",
             "with", "and", "or", "up", "out", "off", "down", "over", "get", "go"}


# ── MW 마크업 제거 ──────────────────────────────────────────────────────
def clean(text: str) -> str:
    """{bc}, {it}…{/it}, {sx|word||}, {a_link|word} 같은 MW 서식 토큰을 걷어낸다."""
    t = re.sub(r"\{dx\}.*?\{/dx\}", "", text)          # 교차참조 블록은 통째로 제거
    t = t.replace("{bc}", "").replace("{ldquo}", "“").replace("{rdquo}", "”")
    t = re.sub(r"\{(?:sx|a_link|d_link|i_link|et_link|mat|dxt)\|([^|}]*)[^}]*\}", r"\1", t)
    t = re.sub(r"\{[^}]*\}", "", t)                     # {it} {/it} {phrase} {wi} ...
    t = re.sub(r"\s*\[=[^\]]*\]", "", t)                 # 예문 뒤 [=풀어쓴 설명]
    return re.sub(r"\s+", " ", t).strip(" ;:")


# ── 구문 매칭 ───────────────────────────────────────────────────────────
def _tokens(phrase: str) -> list[str]:
    words = re.findall(r"[a-z']+", phrase.lower())
    return [IRREGULAR.get(w, w) for w in words if w not in PLACEHOLDERS]


def _target_forms(phrase: str) -> list[str]:
    """찾을 때 허용하는 형태: 원형, 앞 관사 뺀 것, 앞 가벼운 동사 뺀 것."""
    toks = _tokens(phrase)
    forms = [toks]
    if toks and toks[0] in ("a", "an", "the"):
        forms.append(toks[1:])
    if toks and toks[0] in LIGHT_VERBS and len(toks) > 2:
        forms.append(toks[1:])
    return [" ".join(f) for f in forms if f]


def _drp_variants(drp: str) -> set[str]:
    """MW 의 drp 표기를 가능한 모든 평문 형태로 펼친다.

    (just) around the corner   → 괄호는 있어도 되고 없어도 됨
    have/get a corner on       → 슬래시는 택일
    throw (someone) under ...  → 자리표시어는 무시
    """
    forms = [[]]
    for chunk in re.findall(r"\([^)]*\)|[^\s()]+", drp.lower()):
        optional = chunk.startswith("(")
        words = re.findall(r"[a-z'/]+", chunk)
        choices: list[list[str]] = [[]]
        for w in words:
            opts = [o for o in w.split("/") if o and o not in PLACEHOLDERS]
            opts = [IRREGULAR.get(o, o) for o in opts]
            if opts:
                choices = [c + [o] for c in choices for o in opts]
        if optional:
            choices.append([])
        forms = [f + c for f in forms for c in choices]
        if len(forms) > 64:                             # 조합 폭발 방지
            forms = forms[:64]
    return {" ".join(f) for f in forms if f}


def matches(target: str, drp: str) -> bool:
    variants = _drp_variants(drp)
    return any(form in variants for form in _target_forms(target))


# ── 응답 해석 ───────────────────────────────────────────────────────────
def _audio_url(name: str) -> str:
    if name.startswith("bix"):
        sub = "bix"
    elif name.startswith("gg"):
        sub = "gg"
    elif not name[:1].isalpha():
        sub = "number"
    else:
        sub = name[0]
    return AUDIO.format(sub=sub, name=name)


def _senses(defs: list | None) -> list[dict]:
    """def → sseq 를 펼쳐 sense 단위 {text, label, examples} 로 만든다."""
    out = []
    for block in defs or []:
        for seq in block.get("sseq", []):
            for kind, sense in seq:
                if kind == "bs":                        # binding sense
                    sense = sense.get("sense", {})
                elif kind != "sense":
                    continue
                text, examples = "", []
                for part in sense.get("dt", []):
                    if part[0] == "text" and not text:
                        text = clean(part[1])
                    elif part[0] == "vis":
                        examples += [clean(v["t"]) for v in part[1] if v.get("t")]
                    elif part[0] == "uns":              # 용법 노트 안의 예문
                        for note in part[1]:
                            for sub in note:
                                if sub[0] == "vis":
                                    examples += [clean(v["t"]) for v in sub[1] if v.get("t")]
                labels = sense.get("sls", []) + sense.get("lbs", [])
                if text:
                    out.append({"text": text, "label": ", ".join(labels) or None,
                                "examples": examples})
    return out


def _base_word(entry: dict) -> str:
    return entry["meta"]["id"].split(":")[0]


def _result(entry: dict, senses: list[dict], matched: str) -> dict:
    examples: list[str] = []
    for s in senses:                                    # 첫 sense 예문이 부족하면 다음 sense 에서
        examples += [e for e in s["examples"] if e not in examples]
    prs = entry.get("hwi", {}).get("prs") or []
    audio = next((_audio_url(p["sound"]["audio"]) for p in prs if p.get("sound")), None)
    return {
        "matched": matched,
        "definition_en": senses[0]["text"],
        "label": senses[0]["label"],
        "examples": examples,
        "definition_source": {
            "name": SOURCE_NAME,
            "url": PAGE.format(word=urllib.parse.quote(_base_word(entry))),
        },
        "audio": audio,
        "audio_word": _base_word(entry),      # dros 에서 찾았으면 구문이 아니라 기반 단어 발음이다
    }


def cross_refs(entries: list, phrase: str) -> list[str]:
    """정의 대신 "see blessing" 같은 교차참조만 있는 run-on 의 참조 대상."""
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        for dro in e.get("dros", []):
            if matches(phrase, dro.get("drp", "")):
                out += re.findall(r"\{dxt\|([^|}]+)", str(dro.get("def")))
    return [re.sub(r":\d+$", "", r) for r in dict.fromkeys(out)]


def find_in(entries: list, phrase: str) -> dict | None:
    """조회 결과에서 phrase 에 해당하는 표제어 또는 run-on 을 찾는다."""
    dicts = [e for e in entries if isinstance(e, dict) and "meta" in e]

    for e in dicts:                                     # ① 표제어 자체가 구문인 경우
        hw = _base_word(e)
        if len(hw.split()) > 1 and matches(phrase, hw):
            senses = _senses(e.get("def"))
            if senses:
                return _result(e, senses, hw)

    for e in dicts:                                     # ② 기반 단어의 run-on
        for dro in e.get("dros", []):
            if matches(phrase, dro.get("drp", "")):
                senses = _senses(dro.get("def"))
                if senses:
                    return _result(e, senses, dro["drp"])
    return None


# ── 네트워크 ────────────────────────────────────────────────────────────
def _fetch(query: str, key: str) -> list:
    from .http import get_json
    return get_json(API.format(q=urllib.parse.quote(query), key=key))


def _lookup_words(phrase: str) -> list[str]:
    """run-on 을 찾으러 조회해볼 기반 단어들. 긴 내용어부터, 굴절형은 원형도."""
    words = [w for w in _tokens(phrase)
             if w not in STOPWORDS and w not in LIGHT_VERBS and len(w) > 2]
    out = []
    for w in sorted(dict.fromkeys(words), key=len, reverse=True):
        out.append(w)
        for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
            if w.endswith(suf) and len(w) - len(suf) > 2:
                out.append(w[: -len(suf)] + rep)
                break
    return list(dict.fromkeys(out))


def lookup(phrase: str, key: str | None = None, fetch=None,
           max_queries: int = 4) -> tuple[dict | None, int]:
    """(결과 또는 None, 사용한 쿼리 수). fetch 는 테스트에서 바꿔 끼울 수 있다."""
    key = key or os.getenv("MERRIAM_WEBSTER_KEY", "")
    if not key:
        raise RuntimeError("MERRIAM_WEBSTER_KEY 가 없습니다.")
    fetch = fetch or _fetch

    used = 0
    queue = [phrase] + _lookup_words(phrase)
    seen: set[str] = set()
    while queue and used < max_queries:
        q = queue.pop(0)
        if q in seen:
            continue
        seen.add(q)
        entries = fetch(q, key)
        used += 1
        hit = find_in(entries, phrase)
        if hit:
            return hit, used
        queue = cross_refs(entries, phrase) + queue       # 교차참조는 먼저 따라간다
    return None, used
