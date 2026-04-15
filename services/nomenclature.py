from __future__ import annotations

import re
from dataclasses import dataclass

from config import ARTICLE_PREFIX_SUGGESTION, NAME_MAX_LEN


@dataclass
class ArticleValidation:
    ok: bool
    message: str
    suggested_article: str | None = None


_DIGITS_ONLY = re.compile(r"^\d+$")


def is_article_digits_only(article: str) -> bool:
    s = (article or "").strip()
    return bool(s) and _DIGITS_ONLY.match(s) is not None


def validate_article(article: str) -> ArticleValidation:
    s = (article or "").strip()
    if not s:
        return ArticleValidation(False, "Артикул не может быть пустым.")
    if is_article_digits_only(s):
        return ArticleValidation(
            False,
            "Артикул не должен состоять только из цифр. Используйте буквенно-цифровой код.",
            suggested_article=f"{ARTICLE_PREFIX_SUGGESTION}-00001",
        )
    return ArticleValidation(True, "")


def validate_name(name: str) -> tuple[bool, str]:
    s = name or ""
    if not s.strip():
        return False, "Наименование не может быть пустым."
    if len(s) > NAME_MAX_LEN:
        return False, f"Наименование длиннее {NAME_MAX_LEN} символов."
    return True, ""


def suggest_next_article(existing_articles: list[str], prefix: str = ARTICLE_PREFIX_SUGGESTION) -> str:
    """Следующий свободный код вида PREFIX-NNNNN среди уже занятых."""
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    max_n = 0
    for a in existing_articles:
        m = pattern.match((a or "").strip())
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}-{max_n + 1:05d}"
