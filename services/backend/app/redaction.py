import re
from collections.abc import Iterable

from app.security.token import token_matches

REDACTED = "[REDACTED]"
MIN_EXACT_SECRET_LENGTH = 8
HOLD_BACK_CHARS = 32
FORCE_FLUSH_CHARS = 8192
GREENLOOP_TOKEN_LENGTH = 43

PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----[\s\S]{0,4096}?-----END[^-\n]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,200}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,200}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,200}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,200}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,200}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),
]
BEARER = re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9._~+/=-]{8,200}")
AUTHORIZATION = re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)(?!bearer\b)[^\s\"']{8,200}")
KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|client[_-]?secret)"
    r"(\s*[=:]\s*[\"']?)[^\s\"']{6,200}"
)
TRAILING_LABEL = re.compile(
    r"(?i)\b(bearer|authorization|api[_-]?key|secret|token|password|passwd|access[_-]?key"
    r"|client[_-]?secret)\s*[=:]?\s*$"
)
TOKEN_CANDIDATE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")


class Redactor:
    def __init__(self, known_secrets: Iterable[str] = (), token_hash: str = ""):
        self._known = sorted(
            {secret for secret in known_secrets if len(secret) >= MIN_EXACT_SECRET_LENGTH},
            key=len,
            reverse=True,
        )
        self._token_hash = token_hash

    def redact(self, text: str) -> str:
        for secret in self._known:
            text = text.replace(secret, REDACTED)
        for pattern in PATTERNS:
            text = pattern.sub(REDACTED, text)
        text = BEARER.sub(rf"\1\2{REDACTED}", text)
        text = AUTHORIZATION.sub(rf"\1\2{REDACTED}", text)
        text = KEY_VALUE.sub(rf"\1\2{REDACTED}", text)
        if self._token_hash:
            text = TOKEN_CANDIDATE.sub(self._redact_token_candidate, text)
        return text

    def _redact_token_candidate(self, match: re.Match[str]) -> str:
        return REDACTED if token_matches(match.group(0), self._token_hash) else match.group(0)

    def stream(self) -> "StreamRedactor":
        return StreamRedactor(self)


class StreamRedactor:
    def __init__(self, redactor: Redactor):
        self._redactor = redactor
        self._pending = ""

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        split = self._safe_split()
        if split <= 0:
            return ""
        ready, self._pending = self._pending[:split], self._pending[split:]
        return self._redactor.redact(ready)

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        return self._redactor.redact(ready)

    def _safe_split(self) -> int:
        pending = self._pending
        unfinished_key = "-----BEGIN" in pending and "-----END" not in pending
        if unfinished_key and len(pending) < FORCE_FLUSH_CHARS:
            return 0
        limit = len(pending) - HOLD_BACK_CHARS
        if limit <= 0:
            return 0
        boundary = max(pending.rfind(" ", 0, limit), pending.rfind("\n", 0, limit))
        if boundary > 0:
            label = TRAILING_LABEL.search(pending[: boundary + 1])
            return label.start() if label else boundary + 1
        return limit if len(pending) >= FORCE_FLUSH_CHARS else 0


def redact_event_dict(redactor: Redactor):
    def processor(_logger, _method, event_dict):
        return {key: _redact_value(redactor, value) for key, value in event_dict.items()}

    return processor


def _redact_value(redactor: Redactor, value):
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(redactor, item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(redactor, item) for item in value]
    return value
