"""[로컬 PC 전용] 유튜브 자막에서 표현을 뽑고, 그 표현이 나온 장면 링크를 만든다.

YouTube 는 클라우드 IP(GitHub Actions 포함)를 차단하므로 이 스크립트만은
집 PC 에서 돌려야 한다. 결과를 커밋하면 이후 발송은 클라우드에서 계속된다.

  python -m src.sources.youtube                대기열에 쌓인 링크 전부 처리
  python -m src.sources.youtube <URL>          특정 영상만 처리
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import ingest, pronounce, store
from .match import PLACEHOLDERS, phrase_regex

VIDEO_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/))([A-Za-z0-9_-]{11})"
)
SRT_BLOCK_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*\d+:\d+:\d+[,.]\d+\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.S,
)


def video_id(url: str) -> str | None:
    m = VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


# ── 자막 받기 ───────────────────────────────────────────────────────────
def fetch_subtitles(url: str, workdir: Path) -> str | None:
    """yt-dlp 로 영어 자막을 받아 SRT 내용을 돌려준다."""
    if not shutil.which("yt-dlp"):
        print("  yt-dlp 가 없습니다:  pip install yt-dlp")
        return None

    cmd = [
        "yt-dlp", "--skip-download",
        "--write-sub", "--write-auto-sub",
        "--sub-lang", "en.*", "--sub-format", "vtt/srt",
        "--convert-subs", "srt",
        "-o", str(workdir / "sub.%(ext)s"),
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    files = sorted(workdir.glob("*.srt"))
    if not files:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        print(f"  자막을 받지 못했습니다: {detail[-1] if detail else '알 수 없는 오류'}")
        return None
    return files[0].read_text(encoding="utf-8", errors="replace")


def parse_srt(srt: str) -> list[tuple[float, str]]:
    """[(시작초, 대사)] 로 바꾼다. 자동자막의 중복 줄은 걸러낸다."""
    cues: list[tuple[float, str]] = []
    previous = ""
    for h, m, s, ms, body in SRT_BLOCK_RE.findall(srt):
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text == previous:
            continue
        start = int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
        cues.append((start, text))
        previous = text
    return cues


def transcript(cues: list[tuple[float, str]]) -> tuple[str, list[tuple[int, float]]]:
    """대사를 하나로 잇고, (글자위치 → 시작초) 표를 함께 만든다."""
    parts, index = [], []
    pos = 0
    for start, text in cues:
        index.append((pos, start))
        parts.append(text)
        pos += len(text) + 1
    return " ".join(parts), index


# ── 표현이 나온 시점 찾기 ───────────────────────────────────────────────
def locate(phrase: str, full: str, index: list[tuple[int, float]]) -> tuple[float, str] | None:
    """(시작초, 그 표현이 들어간 자막 문장). 없으면 None."""
    m = phrase_regex(phrase).search(full)
    if not m:
        return None
    start = 0.0
    for pos, sec in index:
        if pos > m.start():
            break
        start = sec
    # 표현 앞뒤로 문장 하나 정도를 잘라 예문으로 쓴다 (자동자막엔 마침표가 드물다).
    left = max(full.rfind(". ", 0, m.start()) + 2, m.start() - 90, 0)
    right = full.find(". ", m.end())
    right = min(right + 1 if right != -1 else len(full), m.end() + 90)
    sentence = full[left:right].strip()
    return max(0.0, start - 1.5), sentence      # 조금 앞에서 시작해야 말이 잘리지 않는다


def video_title(url: str) -> str:
    try:
        r = subprocess.run(["yt-dlp", "--skip-download", "--print", "%(title)s", url],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else ""
    except (subprocess.SubprocessError, OSError, IndexError):
        return ""


# ── 영상 하나 처리 ──────────────────────────────────────────────────────
def process(url: str, with_audio: bool = True, limit: int = 10) -> list[dict]:
    vid = video_id(url)
    if not vid:
        print(f"  유튜브 링크가 아닙니다: {url}")
        return []

    with tempfile.TemporaryDirectory() as tmp:
        srt = fetch_subtitles(url, Path(tmp))
        if not srt:
            return []
        cues = parse_srt(srt)

    if not cues:
        print("  자막을 해석하지 못했습니다.")
        return []

    full, index = transcript(cues)
    title = video_title(url) or "유튜브 영상"
    print(f"  자막 {len(cues)}줄 / {len(full):,}자 — {title}")

    items = store.load_expressions()
    have = {e["text"].lower() for e in items} | {k.lower() for k in store.load_known()}
    status = store.load_candidate_status()
    low = full.lower()

    # 1.5만 후보를 전부 정규식으로 돌리면 느리므로, 마지막 단어가 자막에 있는 것만 본다.
    found = []
    for c in store.load_candidates():
        text = c["text"]
        if text.lower() in have or status.get(text.lower(), "").startswith("rejected"):
            continue
        tail = text.lower().split()[-1]
        if tail in PLACEHOLDERS or tail not in low:
            continue
        hit = locate(text, full, index)
        if hit:
            found.append((c, hit))
    print(f"  자막에서 후보 표현 {len(found)}개 발견")

    source = {"type": "youtube", "ref": f"https://youtu.be/{vid}", "title": title}
    added: list[dict] = []
    for c, (at, sentence) in found[:limit]:
        record, reason = ingest.assemble(c["text"], c.get("pos"), origin=source, items=items + added)
        if not record:
            status[c["text"].lower()] = f"rejected: {reason}"
            print(f"    ✗ {c['text']} — {reason}")
            continue
        clip = f"https://youtu.be/{vid}?t={int(at)}"
        record["pronunciation"]["source_clip"] = clip
        scene = {"en": sentence, "ko": None, "ko_origin": None, "audio": None,
                 "source": {"name": f"YouTube — {title}", "url": clip, "kind": "youtube"}}
        # 원본 장면 문장을 첫 예문 자리 바로 뒤에 둔다 (예문 3개 유지).
        record["examples"] = (record["examples"][:1] + [scene] + record["examples"][1:])[:3]
        status[c["text"].lower()] = "used"
        print(f"    ✓ {c['text']:32s} {int(at // 60)}:{int(at % 60):02d}  {sentence[:50]}")
        if with_audio:
            pronounce.enrich(record, with_audio=True, check_hits=False)
        added.append(record)

    store.save_candidate_status(status)
    if added:
        items.extend(added)
        store.save_expressions(items)
        store.append_log("ingested", source="youtube", ref=url, count=len(added))
    return added


# ── 대기열 처리 ─────────────────────────────────────────────────────────
def run_inbox(with_audio: bool = True) -> int:
    inbox = store.load_inbox()
    pending = [i for i in inbox if i["status"] == "pending"]
    if not pending:
        print("대기열이 비어 있습니다. 텔레그램 봇이나 웹에서 유튜브 링크를 보내보세요.")
        return 0

    print(f"대기열 {len(pending)}건 처리\n")
    for item in pending:
        print(f"▶ {item['url']}")
        if not video_id(item["url"]):
            item["status"] = "failed"
            item["error"] = "유튜브 링크가 아님 (기사 링크는 아직 지원하지 않습니다)"
            print(f"  건너뜀 — {item['error']}\n")
            continue
        try:
            added = process(item["url"], with_audio=with_audio)
        except Exception as e:
            item["status"] = "failed"
            item["error"] = str(e)
            print(f"  실패 — {e}\n")
            continue

        if added:
            item["status"] = "processed"
            item["extracted"] = [e["id"] for e in added]
            item["error"] = None
            print(f"  표현 {len(added)}개 추가\n")
        else:
            item["status"] = "failed"
            item["error"] = "추출된 표현 없음 (자막에 후보 표현이 없거나 사전 출처가 없음)"
            print(f"  {item['error']}\n")

    store.save_inbox(inbox)
    done = sum(1 for i in inbox if i["status"] == "processed")
    print(f"완료 — 누적 처리 {done}건")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 자막에서 표현 추출 (로컬 전용)")
    ap.add_argument("url", nargs="?", help="특정 영상만 처리 (생략하면 대기열 전체)")
    ap.add_argument("--no-audio", action="store_true", help="TTS 음성 생성 건너뛰기")
    args = ap.parse_args()

    if args.url:
        added = process(args.url, with_audio=not args.no_audio)
        print(f"\n표현 {len(added)}개 추가")
        return 0 if added else 1
    return run_inbox(with_audio=not args.no_audio)


if __name__ == "__main__":
    sys.exit(main())
