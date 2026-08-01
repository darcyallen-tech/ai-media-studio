"""
Quiet GitHub update check for darcyallen-tech/ai-media-studio.

Fetches latest release/tag (preferred) or latest commit date.
Fails soft when offline. Never downloads installers.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from media_studio.config import (
    APP_BUILD_DATE,
    APP_VERSION,
    GITHUB_REPO,
    GITHUB_URL,
)

# User-Agent required by GitHub API
_UA = "AI-Media-Studio-UpdateCheck/1.0 (+https://github.com/darcyallen-tech/ai-media-studio)"
_TIMEOUT_S = 6.0


@dataclass
class UpdateCheckResult:
    """Outcome of a single check (never raises for network errors)."""

    ok: bool  # True if network + parse succeeded
    update_available: bool
    local_version: str
    remote_label: str  # e.g. "v0.2.0" or "commit 2026-08-02"
    remote_url: str
    message: str  # user-facing one-liner
    error: str = ""  # soft failure detail (empty when ok)
    source: str = ""  # release | tag | commit | none


def _http_json(url: str) -> Any | None:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _UA,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    except Exception:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_semver(label: str) -> tuple[int, int, int] | None:
    s = (label or "").strip()
    if s.lower().startswith("v"):
        s = s[1:]
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _semver_newer(remote: str, local: str) -> bool:
    r = _parse_semver(remote)
    l = _parse_semver(local)
    if r is None or l is None:
        return False
    return r > l


def _parse_iso_date(s: str) -> datetime | None:
    raw = (s or "").strip()
    if not raw:
        return None
    # GitHub: 2026-08-01T12:00:00Z
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    # Local build date: YYYY-MM-DD
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _local_build_dt() -> datetime | None:
    return _parse_iso_date(APP_BUILD_DATE)


def check_github_update(*, force: bool = False) -> UpdateCheckResult:
    """
    Compare local APP_VERSION / APP_BUILD_DATE to GitHub.

    Order: latest release → first tag → latest commit date.
    ``force`` is reserved for UI “check now” (same network path).
    """
    _ = force
    local = (APP_VERSION or "0.0.0").strip()
    repo = GITHUB_REPO
    base = f"https://api.github.com/repos/{repo}"
    html_base = GITHUB_URL.rstrip("/")

    # 1) Latest release
    rel = _http_json(f"{base}/releases/latest")
    if isinstance(rel, dict) and rel.get("tag_name"):
        tag = str(rel.get("tag_name") or "").strip()
        url = str(rel.get("html_url") or f"{html_base}/releases").strip()
        if tag and _semver_newer(tag, local):
            return UpdateCheckResult(
                ok=True,
                update_available=True,
                local_version=local,
                remote_label=tag,
                remote_url=url,
                message=(
                    f"Update available: {tag} (you have {local}). "
                    f"Open GitHub to get the latest."
                ),
                source="release",
            )
        if tag:
            return UpdateCheckResult(
                ok=True,
                update_available=False,
                local_version=local,
                remote_label=tag,
                remote_url=url or html_base,
                message=f"You're up to date ({local}).",
                source="release",
            )

    # 2) Tags (when no formal release)
    tags = _http_json(f"{base}/tags?per_page=5")
    if isinstance(tags, list) and tags:
        tag0 = tags[0] if isinstance(tags[0], dict) else {}
        tag = str(tag0.get("name") or "").strip()
        url = f"{html_base}/releases/tag/{tag}" if tag else html_base
        if tag and _semver_newer(tag, local):
            return UpdateCheckResult(
                ok=True,
                update_available=True,
                local_version=local,
                remote_label=tag,
                remote_url=url,
                message=(
                    f"Newer tag on GitHub: {tag} (you have {local}). "
                    f"Open the repo for details."
                ),
                source="tag",
            )
        if tag and _parse_semver(tag):
            return UpdateCheckResult(
                ok=True,
                update_available=False,
                local_version=local,
                remote_label=tag,
                remote_url=html_base,
                message=f"You're up to date ({local}).",
                source="tag",
            )

    # 3) Latest commit date vs local build date
    commits = _http_json(f"{base}/commits?per_page=1")
    if isinstance(commits, list) and commits and isinstance(commits[0], dict):
        c0 = commits[0]
        sha = str(c0.get("sha") or "")[:7]
        commit = c0.get("commit") if isinstance(c0.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        date_s = str(author.get("date") or "")
        remote_dt = _parse_iso_date(date_s)
        local_dt = _local_build_dt()
        url = str(c0.get("html_url") or html_base)
        label = f"commit {sha}" + (f" · {date_s[:10]}" if date_s else "")
        if remote_dt and local_dt and remote_dt.date() > local_dt.date():
            return UpdateCheckResult(
                ok=True,
                update_available=True,
                local_version=local,
                remote_label=label,
                remote_url=url,
                message=(
                    f"GitHub has newer commits ({date_s[:10]}; "
                    f"your build date is {APP_BUILD_DATE}). "
                    f"Open the repo to update."
                ),
                source="commit",
            )
        if remote_dt is not None:
            return UpdateCheckResult(
                ok=True,
                update_available=False,
                local_version=local,
                remote_label=label,
                remote_url=html_base,
                message=f"You're up to date ({local}, build {APP_BUILD_DATE}).",
                source="commit",
            )

    # Network / empty repo / rate limit
    return UpdateCheckResult(
        ok=False,
        update_available=False,
        local_version=local,
        remote_label="",
        remote_url=html_base,
        message="Could not check for updates (offline or GitHub unreachable).",
        error="fetch_failed",
        source="none",
    )
