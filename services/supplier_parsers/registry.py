from __future__ import annotations

import importlib
import json
from functools import lru_cache
from urllib.parse import urlparse

from config import SUPPLIER_SITES_CONFIG_PATH

from services.supplier_parsers.base import SupplierProductParser
from services.supplier_parsers.generic import GenericSupplierParser


@lru_cache(maxsize=1)
def _load_site_config() -> tuple[str, dict[str, str]]:
    path = SUPPLIER_SITES_CONFIG_PATH
    default = "generic"
    hosts: dict[str, str] = {}
    if not path.is_file():
        return default, hosts
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default, hosts
    if not isinstance(data, dict):
        return default, hosts
    default = str(data.get("default_parser", default)).strip() or default
    raw_hosts = data.get("hosts")
    if isinstance(raw_hosts, dict):
        for k, v in raw_hosts.items():
            hk = str(k).strip().lower()
            pv = str(v).strip()
            if hk and pv:
                hosts[hk] = pv
    return default, hosts


def reload_supplier_site_config() -> None:
    _load_site_config.cache_clear()
    _get_parser_class.cache_clear()


@lru_cache(maxsize=32)
def _get_parser_class(parser_id: str) -> type[SupplierProductParser]:
    if parser_id == "generic":
        return GenericSupplierParser
    try:
        mod = importlib.import_module(f"services.supplier_parsers.sites.{parser_id}")
        cls = getattr(mod, "Parser", None)
        if isinstance(cls, type):
            return cls
    except ModuleNotFoundError:
        pass
    return GenericSupplierParser


def resolve_parser_id_for_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    default, hosts = _load_site_config()
    if host in hosts:
        return hosts[host]
    for h, pid in hosts.items():
        if host == h or host.endswith("." + h):
            return pid
    return default


def get_parser_for_url(url: str) -> SupplierProductParser:
    pid = resolve_parser_id_for_url(url)
    cls = _get_parser_class(pid)
    return cls()
