"""한국어 기계번역 (한국어 ON 일 때만 호출).

MyMemory 무료 API — 키 불필요, 익명은 하루 사용량 제한이 있다.
실측상 이디엄이 든 예문은 직역돼 뜻이 틀어진다
("that's a long shot" → "오래 걸린다는 것"). 그래서 **영영 정의만** 번역하고
예문은 번역하지 않는다. 결과는 ko_origin="machine" 으로 기록하고 "(자동번역)" 을 붙인다.
"""
from __future__ import annotations

import urllib.parse

from .sources.http import get_json

API = "https://api.mymemory.translated.net/get?{query}"


class QuotaExceeded(RuntimeError):
    pass


def en_to_ko(text: str) -> str | None:
    """번역 실패 시 None. 할당량 소진이면 QuotaExceeded."""
    if not text or not text.strip():
        return None
    data = get_json(API.format(query=urllib.parse.urlencode({"q": text[:480], "langpair": "en|ko"})))
    if data.get("quotaFinished"):
        raise QuotaExceeded("MyMemory 일일 번역 한도를 다 썼습니다.")
    if str(data.get("responseStatus")) != "200":
        return None
    out = (data.get("responseData") or {}).get("translatedText") or ""
    # 한도 초과·오류 시 안내 문구를 번역 결과처럼 돌려주는 경우가 있다.
    if not out or "MYMEMORY WARNING" in out.upper() or out.strip() == text.strip():
        return None
    return out.strip()


def fill_korean(exp: dict) -> bool:
    """정의의 한국어가 비어 있으면 채운다. 바뀌었으면 True."""
    changed = False
    try:
        if not exp.get("meaning_ko") and exp.get("definition_en"):
            ko = en_to_ko(exp["definition_en"])
            if ko:
                exp["meaning_ko"], exp["ko_origin"] = ko, "machine"
                changed = True
    except QuotaExceeded as e:
        print(f"  [번역] {e} 나머지는 다음에 채웁니다.")
    except Exception as e:                        # 번역이 안 돼도 발송은 계속한다
        print(f"  [번역] 실패: {e}")
    return changed
