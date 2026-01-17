# sandbox/app/security/network_policy.py
"""
Purpose: Enforce outbound network allowlist (domains) defined in config settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from app.config.settings import get_settings


class NetworkPolicyError(Exception):
    pass


@dataclass(frozen=True)
class AllowedTarget:
    url: str
    hostname: str


def _normalize_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def _is_allowed_host(host: str, allowlist: list[str]) -> bool:
    host = _normalize_host(host)
    if not host:
        return False

    for allowed in allowlist:
        allowed = _normalize_host(allowed)
        if not allowed:
            continue

        if host == allowed:
            return True

        # Allow subdomains of allowed domains
        if host.endswith("." + allowed):
            return True

    return False


def validate_outbound_url(url: str) -> AllowedTarget:
    """
    Validate a URL against the configured outbound allowlist.
    Returns an AllowedTarget if allowed, otherwise raises NetworkPolicyError.
    """
    settings = get_settings()

    if not settings.network.outbound_enabled:
        raise NetworkPolicyError("Outbound network is disabled")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise NetworkPolicyError("Only http/https outbound URLs are permitted")

    host = _normalize_host(parsed.hostname or "")
    if not _is_allowed_host(host, settings.network.domain_allowlist):
        raise NetworkPolicyError("Outbound target not in allowlist")

    return AllowedTarget(url=url, hostname=host)


def validate_git_remote(remote: str) -> str:
    """
    Validate an HTTPS git remote (or git@ style) against the allowlist.
    Returns the remote string if allowed, otherwise raises NetworkPolicyError.
    """
    settings = get_settings()

    if not settings.network.outbound_enabled:
        raise NetworkPolicyError("Outbound network is disabled")

    remote = (remote or "").strip()
    if not remote:
        raise NetworkPolicyError("Empty git remote")

    host: Optional[str] = None

    # https://github.com/org/repo.git
    if remote.startswith("http://") or remote.startswith("https://"):
        parsed = urlparse(remote)
        if parsed.scheme not in {"http", "https"}:
            raise NetworkPolicyError("Only http/https git remotes are permitted")
        host = parsed.hostname

    # git@github.com:org/repo.git
    elif remote.startswith("git@"):
        try:
            after_at = remote.split("@", 1)[1]
            host = after_at.split(":", 1)[0]
        except Exception as exc:
            raise NetworkPolicyError("Invalid git@ remote format") from exc

    else:
        raise NetworkPolicyError("Unsupported git remote format")

    host = _normalize_host(host or "")
    if not _is_allowed_host(host, settings.network.domain_allowlist):
        raise NetworkPolicyError("Git remote host not in allowlist")

    return remote