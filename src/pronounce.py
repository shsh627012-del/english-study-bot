"""발음 4종 세트를 만든다.

① YouGlish 링크  - 실제 유튜브 영상에서 그 표현이 발화되는 순간으로 점프
② 원본 장면 링크 - 유튜브에서 뽑은 표현은 자막 타임스탬프로 (sources/youtube.py 가 채움)
③ 단어 발음      - Wiktionary 의 IPA + Wikimedia Commons 의 원어민 녹음
④ 예문 TTS       - gTTS 로 만든 음성 메시지
"""
from __future__ import annotations

import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import requests

from . import config
from .sources.http import BOT_UA

DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
WIKT_RAW = "https://en.wiktionary.org/w/index.php?title={word}&action=raw"
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/{file}"
YOUGLISH = "https://youglish.com/pronounce/{phrase}/{accent}"
# YouGlish 등은 봇처럼 보이는 User-Agent 를 403 으로 막는다. 브라우저 UA 를 그대로 쓴다.
UA = {"User-Agent": (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)}

# 사전에서 찾아봐야 의미 없는 기능어들
STOPWORDS = {
    "a", "an", "the", "be", "is", "are", "was", "to", "of", "in", "on", "at", "by",
    "for", "with", "and", "or", "it", "its", "my", "your", "his", "her", "their",
    "something", "someone", "somebody", "one", "out", "up", "off", "down", "over",
    # 전치사·부사는 발음을 들어봐야 학습 가치가 없다 (beat around the bush → bush 를 골라야 함)
    "around", "through", "about", "into", "onto", "under", "after", "before", "against",
    "across", "along", "behind", "between", "without", "within", "upon", "past", "like",
}


# ── ① YouGlish ──────────────────────────────────────────
def youglish_url(phrase: str, accent: str | None = None) -> str:
    slug = urllib.parse.quote_plus(phrase.strip().lower())
    return YOUGLISH.format(phrase=slug, accent=accent or config.YOUGLISH_ACCENT)


def youglish_hits(phrase: str) -> int | None:
    """실제 발화 사례 수. AI 가 지어낸 표현을 걸러내는 데 쓴다.

    조회하지 못했을 때는 0 이 아니라 **None** 을 돌려준다.
    YouGlish 는 연속 요청을 받으면 HTTP 200 으로 "Bot detection!" 페이지를
    내려주는데, 이걸 '사례 0건'으로 오해하면 drop the ball 같은
    멀쁳한 표현까지 지어낸 표현으로 보고 버리게 된다.
    """
    try:
        r = requests.get(youglish_url(phrase, "english"), headers=UA, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    if "Bot detection" in r.text:
        return None

    # 정상 페이지는 "... | 4162 pronunciations of ... in English" 형태다.
    m = re.search(r"([\d,]+)\s+pronunciations?\s+of", r.text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    # 진짜로 결과가 없는 경우에만 0 으로 본다.
    if re.search(r"(no results|couldn't find|not found)", r.text, re.I):
        return 0
    return None


# ── ③ 단어 발음 (IPA + 원어민 녹음) ────────────────────────
def _keyword(phrase: str) -> list[str]:
    """사전에서 찾을 후보 단어. 내용어를 길이 순으로."""
    words = re.findall(r"[a-z']+", phrase.lower())
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return sorted(content or words, key=len, reverse=True)


def _lemmas(word: str) -> list[str]:
    """굴절형은 Wiktionary 에 발음이 없다(swamped → swamp)."""
    out = [word]
    if word.endswith("ies"):
        out.append(word[:-3] + "y")
    if word.endswith("ing"):
        out += [word[:-3], word[:-3] + "e"]
    if word.endswith("ed"):
        out += [word[:-2], word[:-1]]
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("s"):
        out.append(word[:-1])
    seen: set[str] = set()
    return [w for w in out if len(w) > 2 and not (w in seen or seen.add(w))]


def _english_section(wikitext: str) -> str:
    """Wiktionary 문서에는 여러 언어가 섮여 있다. 영어 섹션만 잘라낸다."""
    m = re.search(r"^==\s*English\s*==\s*$", wikitext, re.M)
    if not m:
        return ""
    rest = wikitext[m.end():]
    nxt = re.search(r"^==[^=]", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _wiktionary(word: str) -> tuple[str | None, str | None]:
    try:
        # Wikimedia 는 브라우저 흉내 UA 로 연속 요청하면 429 를 준다.
        r = requests.get(WIKT_RAW.format(word=word), headers={"User-Agent": BOT_UA}, timeout=15)
        if r.status_code != 200:
            return None, None
    except requests.RequestException:
        return None, None

    section = _english_section(r.text)
    if not section:
        return None, None

    # IPA: 미국발음(GA)을 우선하되 없으면 첫 번째 것을 쓴다.
    ipa = None
    matches = re.findall(r"\{\{IPA\|en\|(/[^/|}]+/)((?:\|[^}]*)?)\}\}", section)
    for value, attrs in matches:
        if "GA" in attrs or "US" in attrs:
            ipa = value
            break
    if not ipa and matches:
        ipa = matches[0][0]

    # 오디오: en-us-* 파일을 우선한다.
    files = re.findall(r"\{\{audio\|en\|([^|}]+\.(?:ogg|mp3|wav))", section, re.I)
    chosen = next((f for f in files if f.lower().startswith("en-us")), files[0] if files else None)
    audio = COMMONS.format(file=urllib.parse.quote(chosen)) if chosen else None
    return ipa, audio


def _free_dictionary(word: str) -> tuple[str | None, str | None]:
    """dictionaryapi.dev. 빠르지만 522 로 죽어 있는 일이 잦다."""
    try:
        r = requests.get(DICT_API.format(word=word), headers=UA, timeout=10)
        if r.status_code != 200:
            return None, None
        entries = r.json()
    except (requests.RequestException, ValueError):
        return None, None

    ipa = audio = None
    for entry in entries if isinstance(entries, list) else []:
        for ph in entry.get("phonetics", []):
            if not ipa and ph.get("text"):
                ipa = ph["text"]
            if not audio and ph.get("audio"):
                url = ph["audio"]
                audio = f"https:{url}" if url.startswith("//") else url
        if not ipa and entry.get("phonetic"):
            ipa = entry["phonetic"]
    return ipa, audio


def dictionary_lookup(phrase: str) -> tuple[str | None, str | None, str | None]:
    """(IPA, 원어민 녹음 URL, 그 녹음의 단어).

    Wiktionary 가 1순위다 — Wikimedia 인프라라 안정적이고
    Commons 에 실제 원어민 녹음이 붙어 있다.

    IPA 는 **한 단어짜리 표현에만** 붙인다.
    "cut corners" 에 /kʌt/ 만 보여주면 틀린 정보가 되기 때문이다.
    구의 발음은 YouGlish(실제 원어민 발화)와 예문 TTS 가 맡는다.
    """
    single = len(phrase.split()) == 1

    for word in _keyword(phrase)[:2]:
        for lemma in _lemmas(word):
            ipa, audio = _wiktionary(lemma)
            if ipa or audio:
                return (ipa if single else None), audio, word
        ipa, audio = _free_dictionary(word)
        if ipa or audio:
            return (ipa if single else None), audio, word
    return None, None, None


# ── ④ 예문 TTS ──────────────────────────────────────────────────────────
def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _tts(text: str, path: Path) -> None:
    from gtts import gTTS
    gTTS(text=text, lang=config.TTS_LANG, tld=config.TTS_TLD).save(str(path))


def _silence(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
         "-t", str(seconds), str(path)],
        check=True, capture_output=True,
    )


def _download(url: str, path: Path) -> bool:
    try:
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            path.write_bytes(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def build_voice(expression: dict, out_dir: Path | None = None) -> Path | None:
    """표현 + 예문들을 한 파일로 이어붙인 음성을 만든다.

    예문은 Tatoeba 원어민 녹음이 있으면 그걸 쓰고, 없을 때만 gTTS 로 합성한다.
    ffmpeg 이 있으면 OGG/OPUS (텔레그램 '음성 메시지' — 속도 조절 가능).
    ffmpeg 이 없으면 합성음만으로 mp3 를 만든다(샘플레이트가 다른 녹음은 섞을 수 없어서).
    실패하면 None.
    """
    out_dir = out_dir or config.AUDIO
    out_dir.mkdir(parents=True, exist_ok=True)
    work = config.TMP / "tts"
    work.mkdir(parents=True, exist_ok=True)
    eid = expression["id"]
    ffmpeg = _have_ffmpeg()

    parts: list[Path] = []
    human = 0
    try:
        head = work / f"{eid}_0.mp3"
        _tts(expression["text"], head)
        parts.append(head)
        for i, ex in enumerate(expression.get("examples", []), 1):
            p = work / f"{eid}_{i}.mp3"
            audio = (ex.get("audio") or {}).get("url")
            if ffmpeg and audio and _download(audio, p):
                human += 1
            else:
                _tts(ex["en"], p)
            parts.append(p)
    except Exception as e:                       # gTTS 는 네트워크 의존이라 실패할 수 있다
        print(f"  [발음] 음성 준비 실패 ({eid}): {e}")
        return None

    if ffmpeg:
        try:
            gap = work / "_gap.wav"
            _silence(gap, config.GAP_SECONDS)
            inputs, chain = [], []
            seq = []
            for i, p in enumerate(parts):
                if i:
                    seq.append(gap)
                seq.append(p)
            for i, p in enumerate(seq):
                inputs += ["-i", str(p)]
                # 녹음마다 샘플레이트·채널이 달라 그대로는 못 잇는다. 통일한 뒤 잇는다.
                chain.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono[a{i}]")
            joined = "".join(f"[a{i}]" for i in range(len(seq)))
            graph = ";".join(chain) + f";{joined}concat=n={len(seq)}:v=0:a=1[out]"
            out = out_dir / f"{eid}.ogg"
            subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
                 "-c:a", "libopus", "-b:a", "32k", str(out)],
                check=True, capture_output=True,
            )
            if human:
                print(f"  [발음] {eid}: 예문 {human}개는 원어민 녹음")
            return out
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"  [발음] ffmpeg 변환 실패, 합성음 mp3 로 폴백합니다: {e}")
            parts = [parts[0]] + [work / f"{eid}_{i}_tts.mp3" for i in range(1, len(parts))]
            for i, ex in enumerate(expression.get("examples", []), 1):
                _tts(ex["en"], parts[i])

    # 폴백: 합성음 mp3 프레임을 그대로 이어붙인다. 음성 메시지가 아닌 오디오 파일로 전송된다.
    out = out_dir / f"{eid}.mp3"
    with out.open("wb") as dst:
        for p in parts:
            dst.write(p.read_bytes())
    return out


# ── 표현 하나에 발음 정보를 채운다 ──────────────────────────────────────
def enrich(expression: dict, with_audio: bool = True, check_hits: bool = True) -> dict:
    ipa, dict_audio, dict_word = dictionary_lookup(expression["text"])
    pron = expression.setdefault("pronunciation", {})
    pron["ipa"] = pron.get("ipa") or ipa
    pron["youglish"] = youglish_url(expression["text"])
    pron["dict_audio"] = pron.get("dict_audio") or dict_audio
    pron["dict_word"] = pron.get("dict_word") or dict_word
    if check_hits and pron.get("youglish_hits") is None:
        pron["youglish_hits"] = youglish_hits(expression["text"])
    if with_audio and not pron.get("tts_file"):
        path = build_voice(expression)
        if path:
            pron["tts_file"] = f"audio/{path.name}"
    return expression
