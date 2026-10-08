import re

PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    r"AKIA[0-9A-Z]{16}",
    r"gh[pousr]_[A-Za-z0-9]{36,}",
    r"gsk_[A-Za-z0-9]{20,}",
    r"(?i)(api[_-]?key|secret|token|password)(\s*[:=]\s*)['\"]?[^\s'\"]{6,}['\"]?",
]


def redact(text: str) -> str:
    for p in PATTERNS:
        text = re.sub(p, lambda m: "[REDACTED]", text, flags=re.S)
    return text