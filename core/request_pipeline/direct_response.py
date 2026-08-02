"""Tiny conversational responses that should not start a trend-report run."""

from __future__ import annotations

import re

_TRIM = re.compile(r"[^0-9A-Za-z가-힣]+")
_GREETINGS = {"안녕", "안녕하세요", "하이", "반가워", "반갑습니다", "헬로", "hello", "hi"}
_THANKS = {"고마워", "고맙습니다", "감사", "감사합니다", "땡큐", "thanks", "thankyou"}


def direct_response_for(question: str) -> str | None:
    normalized = _TRIM.sub("", question).casefold()
    if normalized in _GREETINGS:
        return "안녕하세요! 궁금한 시장·기술·사업 이슈를 편하게 물어보세요."
    if normalized in _THANKS:
        return "다른 질문도 이어서 물어보세요."
    return None
