# -*- coding: utf-8 -*-
"""Cloak Chromium 可用内核清单，供 WebUI 下拉。"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/CloakHQ/cloakbrowser/releases"
PRO_VERSION_URL = "https://cloakbrowser.dev/api/download/version"
_VERSION_PIN_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")
_TAG_RE = re.compile(r"^chromium-v([0-9]+(?:\.[0-9]+){3,4})(?:-pro)?$")
_CACHE_DIR_RE = re.compile(r"^chromium-([0-9]+(?:\.[0-9]+){3,4})(-pro)?$")


def is_full_chromium_version(value: str) -> bool:
    return bool(_VERSION_PIN_RE.fullmatch(str(value or "").strip()))


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in str(version or "").split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _http_get_json(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 10.0):
    import requests
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _platform_tag() -> str:
    try:
        from cloakbrowser.download import get_platform_tag
        return str(get_platform_tag() or "")
    except Exception:
        return ""


def _cache_dir() -> Path | None:
    try:
        from cloakbrowser.config import get_cache_dir
        return Path(get_cache_dir())
    except Exception:
        try:
            from cloakbrowser.download import get_cache_dir
            return Path(get_cache_dir())
        except Exception:
            return None


def _bundled_chromium_version() -> str:
    try:
        from cloakbrowser.config import CHROMIUM_VERSION
        value = str(CHROMIUM_VERSION or "").strip()
        if is_full_chromium_version(value):
            return value
    except Exception:
        pass
    return ""


def fetch_pro_latest(channel: str = "stable") -> str | None:
    url = PRO_VERSION_URL
    if str(channel or "").strip().lower() == "preview":
        url = f"{PRO_VERSION_URL}?channel=preview"
    headers = {}
    tag = _platform_tag()
    if tag:
        headers["X-Platform"] = tag
    data = _http_get_json(url, headers=headers or None)
    if not isinstance(data, dict):
        return None
    version = str(data.get("version") or "").strip()
    return version if is_full_chromium_version(version) else None


def fetch_github_releases() -> list[dict]:
    data = _http_get_json(GITHUB_API_URL, params={"per_page": 100})
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for rel in data:
        if rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        matched = _TAG_RE.match(tag)
        if not matched:
            continue
        version = matched.group(1)
        key = f"{version}:{'pro' if tag.endswith('-pro') else 'free'}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"version": version, "pro": tag.endswith("-pro")})
    return out


def list_cached_binaries() -> list[dict]:
    cache = _cache_dir()
    if cache is None or not cache.is_dir():
        return []
    out: list[dict] = []
    for path in cache.iterdir():
        if not path.is_dir():
            continue
        matched = _CACHE_DIR_RE.match(path.name)
        if not matched:
            continue
        out.append({"version": matched.group(1), "pro": bool(matched.group(2))})
    return out


def _row_label(row: dict) -> str:
    version = str(row.get("value") or "")
    if row.get("pro"):
        return f"{version} · Pro"
    sources = set(row.get("sources") or [])
    if sources & {"github", "cache"}:
        return f"{version} · 免费"
    return version


def list_chromium_versions(*, current: str = "", license_key: str = "", channel: str = "") -> dict:
    """拼下拉选项。第一项 value 为空，表示 latest。远程失败不抛。"""
    errors: list[str] = []
    items: dict[str, dict] = {}

    def add(version: str, *, pro: bool = False, source: str = "") -> None:
        version = str(version or "").strip()
        if not is_full_chromium_version(version):
            return
        row = items.setdefault(version, {"value": version, "pro": False, "sources": []})
        if pro:
            row["pro"] = True
        if source and source not in row["sources"]:
            row["sources"].append(source)

    latest = ""
    requested_channel = "preview" if str(channel or "").strip().lower() == "preview" else "stable"
    if str(license_key or "").strip():
        try:
            latest = fetch_pro_latest(requested_channel) or ""
            if latest:
                add(latest, pro=True, source="pro")
        except Exception as exc:
            logger.debug("Pro 最新内核探测失败: %s", exc)
            errors.append(f"pro: {type(exc).__name__}: {exc}")

    try:
        for rel in fetch_github_releases():
            add(str(rel.get("version") or ""), pro=bool(rel.get("pro")), source="github")
    except Exception as exc:
        logger.debug("GitHub 内核清单失败: %s", exc)
        errors.append(f"github: {type(exc).__name__}: {exc}")

    try:
        for rel in list_cached_binaries():
            add(str(rel.get("version") or ""), pro=bool(rel.get("pro")), source="cache")
    except Exception as exc:
        logger.debug("本地内核缓存扫描失败: %s", exc)
        errors.append(f"cache: {type(exc).__name__}: {exc}")

    current = str(current or "").strip()
    if current:
        add(current, source="current")

    if not latest:
        free_versions = [version for version, row in items.items() if not row.get("pro")]
        pool = free_versions or list(items)
        if pool:
            latest = max(pool, key=_version_key)
        else:
            latest = _bundled_chromium_version()
            if latest:
                add(latest, source="bundled")

    by_major: dict[int, dict] = {}
    for row in items.values():
        major = _version_key(row["value"])[0]
        prev = by_major.get(major)
        if prev is None or _version_key(row["value"]) > _version_key(prev["value"]):
            by_major[major] = row
        elif prev is not None and _version_key(row["value"]) == _version_key(prev["value"]):
            if row.get("pro"):
                prev["pro"] = True
            for source in row.get("sources") or []:
                if source not in prev["sources"]:
                    prev["sources"].append(source)
    if current and is_full_chromium_version(current):
        current_major = _version_key(current)[0]
        kept = by_major.get(current_major)
        if kept is None or kept["value"] != current:
            by_major[current_major] = items[current]

    ranked = sorted(by_major.values(), key=lambda row: _version_key(row["value"]), reverse=True)
    latest_label = f"latest ({latest})" if latest else "latest"
    versions = [{"value": "", "label": latest_label}]
    for row in ranked:
        versions.append({"value": row["value"], "label": _row_label(row)})
    return {"latest": latest, "versions": versions, "errors": errors}
