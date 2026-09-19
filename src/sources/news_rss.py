"""영어 뉴스 RSS 에서 기사 본문을 가져온다.

유튜브와 달리 뉴스 사이트는 클라우드 IP 를 막지 않으므로
GitHub Actions 안에서 그대로 돌아간다.
"""
from __future__ import annotations

import html
import random
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; english-study-bot/1.0)"}

FEEDS = [
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
]

MIN_ARTICLE_CHARS = 800
MAX_ARTICLE_CHARS = 12000


def _strip_html(fragment: str) -> str:
    return html.unescape(re.sub(r"(?s)<[^>]+>", "", fragment)).strip()


def article_text(url: str) -> str:
    """기사 페이지에서 본문 문단만 추려낸다.

    내비게이션·푸터 텍스트도 <p> 안에 들어 있는 경우가 많아,
    '문장다운 문단'만 남긴다 — 충분히 길고 마침표가 있는 것.
    """
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code != 200:
            return ""
    except requests.RequestException:
        return ""

    body = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>", " ", r.text)
    paragraphs = []
    for raw in re.findall(r"(?is)<p[^>]*>(.*?)</p>", body):
        text = _strip_html(raw)
        text = re.sub(r"\s+", " ", text)
        if len(text) >= 80 and text.count(".") >= 1:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)[:MAX_ARTICLE_CHARS]


def _feed_items(url: str) -> list[dict]:
    try:
        import feedparser
        feed = feedparser.parse(url)
        return [
            {"title": _strip_html(e.get("title", "")), "url": e.get("link", ""),
             "summary": _strip_html(e.get("summary", ""))}
            for e in feed.entries
            if e.get("link")
        ]
    except Exception:
        return []


def fetch_articles(limit: int = 2) -> list[dict]:
    """본문이 충분히 긴 기사만 골라 돌려준다."""
    out: list[dict] = []
    feeds = FEEDS[:]
    random.shuffle(feeds)

    for source, feed_url in feeds:
        for item in _feed_items(feed_url)[:8]:
            if len(out) >= limit:
                return out
            text = article_text(item["url"])
            if len(text) < MIN_ARTICLE_CHARS:
                continue
            out.append({
                "source": source,
                "title": f"{source} — {item['title']}",
                "url": item["url"],
                "text": text,
            })
    return out


def attach_news_examples(expressions: list[dict], articles: int = 8) -> int:
    """풀·학습 중 표현이 실제 기사에 쓰였으면 그 문장을 원문 링크와 함께 예문으로 붙인다.

    카드의 예문이 이미 다 찼으면, 출처가 겹치는 예문 하나를 뉴스 예문으로 바꾼다
    (예문 3개를 가능한 한 서로 다른 출처에서 — 사전 · Tatoeba · 실제 기사).
    """
    from .match import find_sentence

    targets = [e for e in expressions if e.get("status") in ("pool", "active")
               and not any(ex.get("source", {}).get("kind") == "news" for ex in e.get("examples", []))]
    if not targets:
        return 0

    attached = 0
    for article in fetch_articles(limit=articles):
        for exp in targets:
            if any(ex.get("source", {}).get("kind") == "news" for ex in exp["examples"]):
                continue
            sentence = find_sentence(exp["text"], article["text"])
            if not sentence:
                continue
            example = {"en": sentence, "ko": None, "ko_origin": None, "audio": None,
                       "source": {"name": article["source"], "url": article["url"], "kind": "news"}}
            names = [ex["source"]["name"].split(" #")[0] for ex in exp["examples"]]
            if len(exp["examples"]) < 3:
                exp["examples"].append(example)
            else:
                dup = next((i for i in range(len(names) - 1, -1, -1) if names.count(names[i]) > 1), None)
                if dup is None:
                    continue
                exp["examples"][dup] = example
            attached += 1
            print(f"    📰 {exp['text']}: {sentence[:70]}")
    return attached


if __name__ == "__main__":
    for a in fetch_articles(limit=2):
        print(f"\n{'=' * 60}\n{a['title']}\n{a['url']}\n{'-' * 60}")
        print(a["text"][:400] + " ...")
