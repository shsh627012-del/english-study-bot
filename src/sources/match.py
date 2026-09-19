"""실제 문장(뉴스·자막) 안에서 표현이 쓰였는지 찾는다.

  "throw someone under the bus" → "threw him under the bus" 도 잡는다
  "off the top of one's head"   → "off the top of my head" 도 잡는다
"""
from __future__ import annotations

import re

PLACEHOLDERS = {"someone", "somebody", "something", "sb", "sth"}
POSSESSIVES = {"one's", "someone's", "somebody's", "your", "my", "his", "her", "their", "our"}
POSS_RE = r"(?:my|your|his|her|their|our|its|one's|[a-z]+'s)"

IRREGULAR = {
    "be": ["be", "is", "are", "was", "were", "been", "being", "am", "'s", "'re"],
    "go": ["go", "goes", "went", "gone", "going"],
    "get": ["get", "gets", "got", "gotten", "getting"],
    "have": ["have", "has", "had", "having"],
    "make": ["make", "makes", "made", "making"],
    "take": ["take", "takes", "took", "taken", "taking"],
    "throw": ["throw", "throws", "threw", "thrown", "throwing"],
    "blow": ["blow", "blows", "blew", "blown", "blowing"],
    "bite": ["bite", "bites", "bit", "bitten", "biting"],
    "run": ["run", "runs", "ran", "running"],
    "cut": ["cut", "cuts", "cutting"],
    "beat": ["beat", "beats", "beaten", "beating"],
    "keep": ["keep", "keeps", "kept", "keeping"],
    "come": ["come", "comes", "came", "coming"],
    "give": ["give", "gives", "gave", "given", "giving"],
    "put": ["put", "puts", "putting"],
    "drop": ["drop", "drops", "dropped", "dropping"],
    "call": ["call", "calls", "called", "calling"],
}


def _forms(verb: str) -> list[str]:
    if verb in IRREGULAR:
        return IRREGULAR[verb]
    stem = verb[:-1] if verb.endswith("e") else verb
    forms = {verb, verb + "s", verb + "es", verb + "ed", stem + "ed", stem + "ing", verb + "ing"}
    if re.search(r"[^aeiou][aeiou][bdgmnprt]$", verb):          # drop → dropped
        forms |= {verb + verb[-1] + "ed", verb + verb[-1] + "ing"}
    if verb.endswith("y"):
        forms |= {verb[:-1] + "ies", verb[:-1] + "ied"}
    return sorted(forms, key=len, reverse=True)


WORD = r"[\w'’-]+"


def phrase_regex(phrase: str) -> re.Pattern:
    words = phrase.lower().split()
    out = ""
    for i, w in enumerate(words):
        last = i == len(words) - 1
        if w in PLACEHOLDERS:
            # 자리표시어 = 1~3 단어. 뒤에 올 단어와의 공백까지 여기서 먹는다.
            out += WORD if last else rf"(?:{WORD}\s+){{1,3}}?"
            continue
        if w in POSSESSIVES:
            out += POSS_RE
        elif i == 0 and len(words) > 1:
            out += "(?:" + "|".join(map(re.escape, _forms(w))) + ")"
        else:
            out += re.escape(w)
        if not last:
            out += r"\s+"
    return re.compile(r"\b" + out + r"\b", re.I)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?][\"”’)]?)\s+(?=[A-Z“\"])", text) if s.strip()]


def find_sentence(phrase: str, text: str, min_len: int = 25, max_len: int = 220) -> str | None:
    pat = phrase_regex(phrase)
    for s in split_sentences(text):
        if min_len <= len(s) <= max_len and pat.search(s):
            return s
    return None
