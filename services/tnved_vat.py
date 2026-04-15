from __future__ import annotations

"""
Подсказка ставки НДС по коду ТН ВЭД для РФ.

1) Опционально: HTTP `NSI_TNVED_VAT_LOOKUP_URL` (GET с `{code}` в шаблоне).
2) Файл `data/tnved_vat_ru.json` (или путь из `NSI_TNVED_VAT_CONFIG`).
3) Встроенный запасной набор, если файла нет.

Юридически точная ставка — всегда с бухгалтером/классификатором.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from config import TNVED_VAT_CONFIG_PATH, TNVED_VAT_LOOKUP_TIMEOUT, TNVED_VAT_LOOKUP_URL

_DIGITS = re.compile(r"^\d{4,10}$")

_BUILTIN_10: frozenset[str] = frozenset(
    {
        "01",
        "02",
        "03",
        "04",
        "05",
        "09",
        "10",
        "11",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
    }
)


@dataclass(frozen=True)
class TnvedVatRules:
    country: str
    default_vat_percent: float
    vat_10_two_digit_prefixes: frozenset[str]
    exact_code_vat_percent: dict[str, float]
    prefix_vat_percent: list[tuple[str, float]]


_rules_mtime: float | None = None
_rules_cached: TnvedVatRules | None = None


def reload_tnved_vat_rules() -> None:
    """Сброс кэша после правки JSON (можно вызвать из UI)."""
    global _rules_mtime, _rules_cached
    _rules_mtime = None
    _rules_cached = None


def _builtin_rules() -> TnvedVatRules:
    return TnvedVatRules(
        country="RU",
        default_vat_percent=20.0,
        vat_10_two_digit_prefixes=_BUILTIN_10,
        exact_code_vat_percent={},
        prefix_vat_percent=[],
    )


def _parse_rules_payload(data: dict[str, Any]) -> TnvedVatRules:
    country = str(data.get("country", "RU"))
    default_v = float(data.get("default_vat_percent", 20))
    prefixes_raw = data.get("vat_10_two_digit_prefixes") or []
    vat_10 = frozenset(str(p).strip() for p in prefixes_raw if str(p).strip())
    exact: dict[str, float] = {}
    for k, v in (data.get("exact_code_vat_percent") or {}).items():
        nk = normalize_tnved(str(k))
        if nk:
            exact[nk] = float(v)
    prefix_rules: list[tuple[str, float]] = []
    for row in data.get("prefix_vat_percent") or []:
        if not isinstance(row, dict):
            continue
        p = str(row.get("prefix", "")).strip()
        if p and row.get("vat_percent") is not None:
            prefix_rules.append((p, float(row["vat_percent"])))
    prefix_rules.sort(key=lambda x: -len(x[0]))
    if not vat_10:
        vat_10 = _BUILTIN_10
    return TnvedVatRules(
        country=country,
        default_vat_percent=default_v,
        vat_10_two_digit_prefixes=vat_10,
        exact_code_vat_percent=exact,
        prefix_vat_percent=prefix_rules,
    )


def load_tnved_vat_rules() -> TnvedVatRules:
    global _rules_mtime, _rules_cached
    path = TNVED_VAT_CONFIG_PATH
    if not path.is_file():
        return _builtin_rules()
    mtime = path.stat().st_mtime
    if _rules_cached is not None and _rules_mtime == mtime:
        return _rules_cached
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = _parse_rules_payload(data if isinstance(data, dict) else {})
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        rules = _builtin_rules()
    _rules_mtime = mtime
    _rules_cached = rules
    return rules


def normalize_tnved(code: str | None) -> str | None:
    if not code:
        return None
    s = re.sub(r"\D", "", str(code).strip())
    if len(s) < 4:
        return None
    return s[:10]


def _remote_vat_percent(code: str) -> tuple[float | None, str]:
    url_tpl = TNVED_VAT_LOOKUP_URL
    if not url_tpl:
        return None, ""
    try:
        url = url_tpl.format(code=code)
    except (KeyError, ValueError):
        url = url_tpl.replace("{code}", code)
    try:
        with httpx.Client(timeout=TNVED_VAT_LOOKUP_TIMEOUT) as client:
            r = client.get(url, headers={"User-Agent": "NSI-TNVED/1.0"})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None, ""
    if isinstance(data, dict):
        for key in ("vat_percent", "vat", "nds", "VAT"):
            if key in data and data[key] is not None:
                try:
                    return float(data[key]), "remote_json"
                except (TypeError, ValueError):
                    pass
    return None, ""


def suggest_vat_percent_by_tnved(tnved: str | None) -> float | None:
    n = normalize_tnved(tnved)
    if not n or _DIGITS.fullmatch(n) is None:
        return None
    remote, _src = _remote_vat_percent(n)
    if remote is not None:
        return remote
    rules = load_tnved_vat_rules()
    if n in rules.exact_code_vat_percent:
        return rules.exact_code_vat_percent[n]
    for pref, v in rules.prefix_vat_percent:
        if n.startswith(pref):
            return v
    prefix2 = n[:2]
    if prefix2 in rules.vat_10_two_digit_prefixes:
        return 10.0
    return rules.default_vat_percent


def describe_tnved_hint(tnved: str | None) -> str:
    n = normalize_tnved(tnved)
    if not n:
        return "Введите код ТН ВЭД (РФ / ЕАЭС) — подсказка НДС из настроек `data/tnved_vat_ru.json` или сервиса `NSI_TNVED_VAT_LOOKUP_URL`."
    v = suggest_vat_percent_by_tnved(tnved)
    if v is None:
        return "Код не распознан — ставку НДС задайте вручную."
    src = []
    if TNVED_VAT_LOOKUP_URL:
        src.append("внешний URL")
    if TNVED_VAT_CONFIG_PATH.is_file():
        src.append(str(TNVED_VAT_CONFIG_PATH.name))
    src_txt = ", ".join(src) if src else "встроенные правила"
    return f"РФ: для кода {n} предлагается НДС **{v:g}%** (источник: {src_txt}). Проверьте по актуальному законодательству."
