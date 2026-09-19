"""출처 모듈들이 같이 쓰는 HTTP 헬퍼. 표준 라이브러리만 쓴다."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# 사이트마다 요구가 정반대다.
#  - YouGlish·Tatoeba 는 봇처럼 보이는 UA 를 막는다 → 브라우저 UA
#  - Wikimedia 는 브라우저 흉내를 싫어하고, 정체를 밝힌 UA 를 요구한다 → BOT_UA
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BOT_UA = "EnglishStudyBot/1.0 (personal non-commercial vocabulary tool; python-urllib)"


class HTTPError(RuntimeError):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status}: {url}")
        self.status = status


def get_text(url: str, timeout: float = 25, retries: int = 4, ua: str = BROWSER_UA) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        wait = 2 ** attempt
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:          # 4xx 는 재시도해도 소용없다
                raise HTTPError(e.code, url) from None
            last = HTTPError(e.code, url)
            retry_after = e.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = max(wait, int(retry_after))
            elif e.code == 429:
                wait = max(wait, 10 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(wait)
    raise last or RuntimeError(url)


def get_json(url: str, timeout: float = 25, ua: str = BROWSER_UA):
    return json.loads(get_text(url, timeout=timeout, ua=ua))
