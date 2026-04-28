"""Validate local commit messages against project conventions."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CONVENTIONAL_SUBJECT = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|build|ci|perf|style|revert)(\([^)]+\))?: .+"
)
HANGUL = re.compile(r"[가-힣]")
NARRATIVE_ENDING = re.compile(r"(했습니다|하였다|하였습니다|했다|함)\.?$")
URL_OR_HOST = re.compile(r"https?://|www\.", re.IGNORECASE)
IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HOST_PORT = re.compile(r"\b[\w.-]+:\d{2,5}\b")
SENSITIVE_NUMBER = re.compile(r"\b\d{4,5}\b")
SENSITIVE_TERMS = re.compile(
    r"(api[-_ ]?key|token|secret|password|credential|토큰|비밀번호|시크릿|인증키)",
    re.IGNORECASE,
)


def _non_comment_lines(message: str) -> list[str]:
    return [line.rstrip() for line in message.splitlines() if not line.startswith("#")]


def validate(message: str) -> list[str]:
    lines = _non_comment_lines(message)
    while lines and not lines[-1]:
        lines.pop()

    errors: list[str] = []
    if not lines or not lines[0].strip():
        return ["커밋 제목이 비어 있음"]

    subject = lines[0].strip()
    if len(subject) > 50:
        errors.append("제목은 50자 이하")
    if not CONVENTIONAL_SUBJECT.match(subject):
        errors.append("제목은 Conventional Commit 형식 필요: <type>: <한글 제목>")
    if not HANGUL.search(subject):
        errors.append("제목은 한글로 작성")

    if len(lines) < 3 or lines[1] != "":
        errors.append("제목 다음에 빈 줄 1개 필요")
    body_lines = [line for line in lines[2:] if line.strip()] if len(lines) >= 3 else []
    if not body_lines:
        errors.append("본문 bullet 필요")
    for line in body_lines:
        if not line.startswith("- "):
            errors.append("본문은 '- ' bullet 형식만 사용")
            break
        if not HANGUL.search(line):
            errors.append("본문 bullet은 한글 설명 포함")
            break
        if NARRATIVE_ENDING.search(line):
            errors.append("본문 bullet은 서술형 과거시제 종결 금지")
            break

    full_message = "\n".join(lines)
    if URL_OR_HOST.search(full_message) or IP_ADDRESS.search(full_message):
        errors.append("커밋 메시지에 URL 또는 IP 주소 노출 금지")
    if HOST_PORT.search(full_message) or SENSITIVE_NUMBER.search(full_message):
        errors.append("커밋 메시지에 포트/운영 숫자 노출 금지")
    if SENSITIVE_TERMS.search(full_message):
        errors.append("커밋 메시지에 키/토큰/비밀값 관련 세부명 노출 금지")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 2
    message = Path(sys.argv[1]).read_text(encoding="utf-8")
    errors = validate(message)
    if errors:
        print("커밋 메시지 규칙 위반:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
