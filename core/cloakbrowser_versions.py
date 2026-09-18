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
        from cloakbrowser.config import get_platform_tag
        return str(get_platform_tag() or "")
    except Exception:
        try:
            from cloakbrowser.download import get_platform_tag as download_get_platform_tag
            return str(download_get_platform_tag() or "")
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
        from cloakbrowser.config import get_chromium_version
        value = str(get_chromium_version() or "").strip()
        if is_full_chromium_version(value):
            return value
    except Exception:
        pass
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


def _platform_asset_name(platform_tag: str | None = None) -> str:
    tag = str(platform_tag or _platform_tag() or "").strip()
    return f"cloakbrowser-{tag}.tar.gz" if tag else ""


def _release_has_platform_asset(rel: dict, asset_name: str) -> bool:
    if not asset_name:
        return False
    assets = rel.get("assets") or []
    if not isinstance(assets, list):
        return False
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name == asset_name:
            return True
    return False


def fetch_github_releases() -> list[dict]:
    data = _http_get_json(GITHUB_API_URL, params={"per_page": 100})
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    asset_name = _platform_asset_name()
    for rel in data:
        if rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        matched = _TAG_RE.match(tag)
        if not matched:
            continue
        version = matched.group(1)
        is_pro = tag.endswith("-pro")
        if not is_pro and not _release_has_platform_asset(rel, asset_name):
            continue
        key = f"{version}:{'pro' if is_pro else 'free'}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"version": version, "pro": is_pro, "has_platform_asset": (not is_pro)})
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


def _row_is_runnable(row: dict, *, has_license: bool) -> bool:
    sources = set(row.get("sources") or [])
    if has_license:
        return bool(row.get("pro"))
    if row.get("pro") and "cache" not in sources:
        return False
    if sources & {"github", "cache"}:
        return True
    if "bundled" in sources:
        return True
    return False


def _row_label(row: dict, *, has_license: bool) -> str:
    version = str(row.get("value") or "")
    runnable = _row_is_runnable(row, has_license=has_license)
    if not runnable:
        return f"{version} · 不可用"
    if row.get("pro"):
        return f"{version} · Pro"
    sources = set(row.get("sources") or [])
    if sources & {"github", "cache", "bundled"}:
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

    has_license = bool(str(license_key or "").strip())
    latest = ""
    requested_channel = "preview" if str(channel or "").strip().lower() == "preview" else "stable"
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
        pool = [version for version in items if is_full_chromium_version(version)]
        if pool:
            latest = max(pool, key=_version_key)

    by_major: dict[int, dict] = {}
    for row in items.values():
        if not _row_is_runnable(row, has_license=has_license):
            continue
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
        versions.append({"value": row["value"], "label": _row_label(row, has_license=has_license)})
    return {"latest": latest, "versions": versions, "errors": errors}


def resolve_launch_browser_version(*, current: str = "", license_key: str = "", channel: str = "") -> str:
    """空配置=latest：返回探测到的最新完整号，避免 cloakbrowser 回落到捆绑 146。"""
    current = str(current or "").strip()
    if is_full_chromium_version(current):
        return current
    payload = list_chromium_versions(current=current, license_key=license_key, channel=channel)
    latest = str(payload.get("latest") or "").strip()
    return latest if is_full_chromium_version(latest) else ""
