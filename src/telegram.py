"""Telegram Bot API 래퍼. 필요한 메서드만 얇게 감쌌다."""
from __future__ import annotations

import html
import sys
import time
from pathlib import Path
from typing import Any

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30


class TelegramError(RuntimeError):
    pass


def _call(method: str, files: dict | None = None, **params: Any) -> Any:
    if not config.TELEGRAM_BOT_TOKEN:
        raise TelegramError("TELEGRAM_BOT_TOKEN 이 비어 있습니다. .env 또는 GitHub Secrets 를 확인하세요.")

    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    payload = {k: v for k, v in params.items() if v is not None}

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.post(url, data=payload, files=files, timeout=TIMEOUT)
            body = r.json()
            if body.get("ok"):
                return body["result"]

            # 429 는 retry_after 만큼 기다렸다가 재시도한다.
            if r.status_code == 429:
                wait = body.get("parameters", {}).get("retry_after", 3)
                time.sleep(wait)
                continue
            raise TelegramError(f"{method} 실패: {body.get('description')}")
        except requests.RequestException as e:      # 네트워크 오류만 재시도
            last_error = e
            time.sleep(2 ** attempt)
        if files:  # 파일 핸들은 한 번 읽으면 소진되므로 재시도할 수 없다
            break

    raise TelegramError(f"{method} 호출 실패: {last_error}")


# ── 보내기 ──────────────────────────────────────────────────────────────
def send_message(text: str, keyboard: list[list[dict]] | None = None,
                 chat_id: str | None = None, preview: bool = False) -> dict:
    import json as _json
    return _call(
        "sendMessage",
        chat_id=chat_id or config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
        link_preview_options=_json.dumps({"is_disabled": not preview}),
        reply_markup=_json.dumps({"inline_keyboard": keyboard}) if keyboard else None,
    )


def send_voice(path: Path, caption: str | None = None, chat_id: str | None = None) -> dict:
    """OGG/OPUS 여야 '음성 메시지'로 뜬다(속도 조절·파형 지원).
    변환 실패로 mp3 가 넘어오면 sendAudio 로 폴백한다."""
    method = "sendVoice" if path.suffix.lower() == ".ogg" else "sendAudio"
    field = "voice" if method == "sendVoice" else "audio"
    with path.open("rb") as f:
        return _call(
            method,
            files={field: (path.name, f)},
            chat_id=chat_id or config.TELEGRAM_CHAT_ID,
            caption=caption,
            parse_mode="HTML" if caption else None,
        )


# ── 받기 ────────────────────────────────────────────────────────────────
def get_updates(offset: int) -> list[dict]:
    import json as _json
    return _call(
        "getUpdates",
        offset=offset,
        timeout=0,
        allowed_updates=_json.dumps(["message", "callback_query"]),
    )


def answer_callback_query(callback_id: str, text: str = "") -> Any:
    """버튼 누름에 대한 즉답. 텔레그램은 몇 초 안에만 받아준다.

    폴링 주기(20분)로는 거의 항상 만료되므로 실패해도 무시한다 —
    실제 피드백은 edit_reply_markup 으로 버튼을 ✅ 로 바꾸는 쪽이 맡는다.
    """
    try:
        return _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except TelegramError as e:
        if "too old" in str(e) or "query ID is invalid" in str(e):
            return None
        raise


def edit_reply_markup(chat_id: int | str, message_id: int,
                      keyboard: list[list[dict]] | None) -> Any:
    import json as _json
    try:
        return _call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=_json.dumps({"inline_keyboard": keyboard or []}),
        )
    except TelegramError as e:
        # 이미 같은 내용이면 텔레그램이 에러를 준다. 무시해도 되는 경우.
        if "not modified" in str(e):
            return None
        raise


def esc(text: str) -> str:
    """parse_mode=HTML 이므로 사용자 텍스트는 반드시 이스케이프한다."""
    return html.escape(str(text), quote=False)


# ── CLI: 내 chat_id 찾기 ────────────────────────────────────────────────
def _whoami() -> None:
    me = _call("getMe")
    print(f"봇: @{me['username']} ({me['first_name']})")
    updates = _call("getUpdates", timeout=0)
    if not updates:
        print("\n받은 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
        return
    seen: dict[int, str] = {}
    for u in updates:
        chat = (u.get("message") or u.get("callback_query", {}).get("message") or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    print("\n발견한 chat_id:")
    for cid, name in seen.items():
        print(f"  TELEGRAM_CHAT_ID={cid}   ({name})")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "whoami":
        _whoami()
    else:
        print("사용법: python -m src.telegram whoami")
