"""
Quiet GitHub update check for darcyallen-tech/ai-media-studio.

Preference order for “are we behind?”:
  1. APP_VERSION vs latest GitHub release tag / first tag (semver)
  2. APP_GIT_SHA (or live git HEAD) vs latest commit SHA
  3. APP_BUILD_DATE vs commit calendar day — same day = current unless SHA differs

Fails soft when offline. Never downloads installers. Banner only when remote
is actually newer (version or different newer SHA), not a later clock stamp alone.
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
    APP_GIT_SHA,
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
    local_sha: str = ""
    remote_sha: str = ""


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


def _semver_cmp(a: str, b: str) -> int | None:
    """Return 1 if a>b, -1 if a<b, 0 if equal; None if either unparsable."""
    pa, pb = _parse_semver(a), _parse_semver(b)
    if pa is None or pb is None:
        return None
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def _semver_newer(remote: str, local: str) -> bool:
    c = _semver_cmp(remote, local)
    return c is not None and c > 0


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


def _norm_sha(s: str) -> str:
    return re.sub(r"[^0-9a-f]", "", (s or "").strip().lower())


def _sha_match(local: str, remote: str) -> bool:
    """True if local and remote refer to the same commit (prefix match, min 7)."""
    a, b = _norm_sha(local), _norm_sha(remote)
    if len(a) < 7 or len(b) < 7:
        return False
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _local_sha() -> str:
    """Prefer config APP_GIT_SHA; refresh from git when empty."""
    sha = (APP_GIT_SHA or "").strip()
    if sha:
        return sha
    try:
        from media_studio.config import _resolve_app_git_sha

        return (_resolve_app_git_sha() or "").strip()
    except Exception:
        return ""


def _current_result(
    *,
    local: str,
    remote_label: str,
    remote_url: str,
    source: str,
    local_sha: str = "",
    remote_sha: str = "",
    detail: str = "",
) -> UpdateCheckResult:
    msg = f"You're up to date ({local})."
    if detail:
        msg = f"You're up to date ({detail})."
    return UpdateCheckResult(
        ok=True,
        update_available=False,
        local_version=local,
        remote_label=remote_label,
        remote_url=remote_url,
        message=msg,
        source=source,
        local_sha=local_sha,
        remote_sha=remote_sha,
    )


def _update_result(
    *,
    local: str,
    remote_label: str,
    remote_url: str,
    message: str,
    source: str,
    local_sha: str = "",
    remote_sha: str = "",
) -> UpdateCheckResult:
    return UpdateCheckResult(
        ok=True,
        update_available=True,
        local_version=local,
        remote_label=remote_label,
        remote_url=remote_url,
        message=message,
        source=source,
        local_sha=local_sha,
        remote_sha=remote_sha,
    )


def check_github_update(*, force: bool = False) -> UpdateCheckResult:
    """
    Compare local APP_VERSION / APP_GIT_SHA to GitHub.

    Order: latest release (semver) → first tag (semver) → latest commit SHA
    (then same-day build-date fallback only when SHA unknown or differs).
    ``force`` is reserved for UI “check now” (same network path).
    """
    _ = force
    local = (APP_VERSION or "0.0.0").strip()
    local_sha = _local_sha()
    repo = GITHUB_REPO
    base = f"https://api.github.com/repos/{repo}"
    html_base = GITHUB_URL.rstrip("/")

    # 1) Latest release — authoritative when a tag exists
    rel = _http_json(f"{base}/releases/latest")
    if isinstance(rel, dict) and rel.get("tag_name"):
        tag = str(rel.get("tag_name") or "").strip()
        url = str(rel.get("html_url") or f"{html_base}/releases").strip()
        if tag and _semver_newer(tag, local):
            return _update_result(
                local=local,
                remote_label=tag,
                remote_url=url,
                message=(
                    f"Update available: {tag} (you have {local}). "
                    f"Open GitHub to get the latest."
                ),
                source="release",
                local_sha=local_sha,
            )
        if tag and _parse_semver(tag) is not None:
            # Equal or local ahead of latest release → current (do not date-scare)
            return _current_result(
                local=local,
                remote_label=tag,
                remote_url=url or html_base,
                source="release",
                local_sha=local_sha,
                detail=f"{local} · remote {tag}",
            )

    # 2) Tags (when no formal release)
    tags = _http_json(f"{base}/tags?per_page=5")
    if isinstance(tags, list) and tags:
        tag0 = tags[0] if isinstance(tags[0], dict) else {}
        tag = str(tag0.get("name") or "").strip()
        url = f"{html_base}/releases/tag/{tag}" if tag else html_base
        if tag and _semver_newer(tag, local):
            return _update_result(
                local=local,
                remote_label=tag,
                remote_url=url,
                message=(
                    f"Newer tag on GitHub: {tag} (you have {local}). "
                    f"Open the repo for details."
                ),
                source="tag",
                local_sha=local_sha,
            )
        if tag and _parse_semver(tag) is not None:
            return _current_result(
                local=local,
                remote_label=tag,
                remote_url=html_base,
                source="tag",
                local_sha=local_sha,
                detail=f"{local} · remote {tag}",
            )
        # Tag may also carry a commit SHA (object.sha)
        if isinstance(tag0, dict):
            obj = tag0.get("commit") if isinstance(tag0.get("commit"), dict) else {}
            tag_sha = str(obj.get("sha") or "").strip()
            if tag_sha and local_sha and _sha_match(local_sha, tag_sha):
                return _current_result(
                    local=local,
                    remote_label=tag or tag_sha[:7],
                    remote_url=html_base,
                    source="tag",
                    local_sha=local_sha,
                    remote_sha=tag_sha,
                    detail=f"{local} · {local_sha[:7]}",
                )

    # 3) Latest commit — SHA first, date only as same-day-safe fallback
    commits = _http_json(f"{base}/commits?per_page=1")
    if isinstance(commits, list) and commits and isinstance(commits[0], dict):
        c0 = commits[0]
        remote_sha = str(c0.get("sha") or "").strip()
        short = remote_sha[:7] if remote_sha else ""
        commit = c0.get("commit") if isinstance(c0.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        date_s = str(author.get("date") or "")
        remote_dt = _parse_iso_date(date_s)
        local_dt = _local_build_dt()
        url = str(c0.get("html_url") or html_base)
        label = f"commit {short}" + (f" · {date_s[:10]}" if date_s else "")

        # 3a) SHA match → definitely current (smoke: latest pull, no banner)
        if local_sha and remote_sha and _sha_match(local_sha, remote_sha):
            return _current_result(
                local=local,
                remote_label=label,
                remote_url=html_base,
                source="commit",
                local_sha=local_sha,
                remote_sha=remote_sha,
                detail=f"{local} · {local_sha[:7]}",
            )

        # 3b) SHA differs (or local SHA unknown) — use calendar day carefully
        if remote_dt is not None and local_dt is not None:
            rday = remote_dt.date()
            lday = local_dt.date()
            if rday < lday:
                # Local build day is after remote tip (dev ahead / clock skew)
                return _current_result(
                    local=local,
                    remote_label=label,
                    remote_url=html_base,
                    source="commit",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                    detail=f"{local}, build {APP_BUILD_DATE}",
                )
            if rday == lday:
                # Same calendar day: current unless we know SHA differs
                if local_sha and remote_sha and not _sha_match(local_sha, remote_sha):
                    return _update_result(
                        local=local,
                        remote_label=label,
                        remote_url=url,
                        message=(
                            f"GitHub tip differs ({short}; you have {local_sha[:7]}). "
                            f"Open the repo to update."
                        ),
                        source="commit",
                        local_sha=local_sha,
                        remote_sha=remote_sha,
                    )
                # No SHA or match already handled — same day without proof of lag
                return _current_result(
                    local=local,
                    remote_label=label,
                    remote_url=html_base,
                    source="commit",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                    detail=f"{local}, build {APP_BUILD_DATE}",
                )
            # rday > lday — remote commit is on a later calendar day
            if local_sha and remote_sha and not _sha_match(local_sha, remote_sha):
                return _update_result(
                    local=local,
                    remote_label=label,
                    remote_url=url,
                    message=(
                        f"GitHub has newer commits ({short} · {date_s[:10]}; "
                        f"you have {local_sha[:7]}). Open the repo to update."
                    ),
                    source="commit",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            if not local_sha:
                # No local SHA: later calendar day is the only signal
                return _update_result(
                    local=local,
                    remote_label=label,
                    remote_url=url,
                    message=(
                        f"GitHub has newer commits ({date_s[:10]}; "
                        f"your build date is {APP_BUILD_DATE}). "
                        f"Open the repo to update."
                    ),
                    source="commit",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            # Have local SHA but couldn't match logic — treat as current
            return _current_result(
                local=local,
                remote_label=label,
                remote_url=html_base,
                source="commit",
                local_sha=local_sha,
                remote_sha=remote_sha,
                detail=f"{local} · {local_sha[:7]}",
            )

        # Date missing: SHA differ alone is weak without graph; stay quiet
        if remote_sha:
            return _current_result(
                local=local,
                remote_label=label,
                remote_url=html_base,
                source="commit",
                local_sha=local_sha,
                remote_sha=remote_sha,
                detail=local if not local_sha else f"{local} · {local_sha[:7]}",
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
        local_sha=local_sha,
    )
