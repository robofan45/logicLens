#!/usr/bin/env python3
"""Target guard for six-gate-build (gates 4 and 6).

Load tests and attack probes may only hit the build under test: a server on this
machine (loopback) or a host the user has explicitly said they own, given via the
SIX_GATE_ALLOWED_HOSTS environment variable (comma-separated) or --allow.
Everything else is refused (fail closed).

This is a safety net against mistakes (a typo, a pasted production URL, a redirect
to a third party). It is not a sandbox against a hostile operator, and it cannot
tell whether something listening on localhost is really a test instance (an SSH
tunnel to production also looks like localhost), so still check what is on the port.

    python target_guard.py http://127.0.0.1:8000        -> exit 0, prints normalized URL
    python target_guard.py https://staging.example.com --allow staging.example.com
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from typing import Iterable, Optional
from urllib.parse import urlsplit

ENV_ALLOWLIST = "SIX_GATE_ALLOWED_HOSTS"
MAX_URL_LENGTH = 2048


class TargetNotAllowed(ValueError):
    """The target is not loopback and not explicitly allow-listed."""


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def allowed_hosts(extra: Optional[Iterable[str]] = None) -> set:
    """Exact host names the user has declared as theirs. No wildcards, by design."""
    entries = os.environ.get(ENV_ALLOWLIST, "").split(",") + list(extra or [])
    hosts = set()
    for entry in entries:
        entry = entry.strip()
        if "://" in entry:
            try:
                entry = urlsplit(entry).hostname or ""
            except ValueError:
                continue
        entry = _normalize_host(entry)
        if entry:
            hosts.add(entry)
    return hosts


def is_loopback_host(host: str) -> bool:
    """True for 'localhost' and canonical loopback/unspecified IP literals only."""
    host = _normalize_host(host)
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Other names, and non-canonical spellings such as 127.1 or 0x7f000001, fail closed.
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_unspecified


def check_target(url, extra_allowed: Optional[Iterable[str]] = None) -> str:
    """Return the normalized base URL if it is safe to target, else raise TargetNotAllowed."""
    if not isinstance(url, str) or not url.strip():
        raise TargetNotAllowed("No target URL given.")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise TargetNotAllowed("Target URL is implausibly long.")
    # Reject rather than let different URL parsers disagree about what these mean.
    if "\\" in url or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        raise TargetNotAllowed("Target URL contains whitespace, control characters or backslashes.")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for malformed or out-of-range ports
    except ValueError as exc:
        raise TargetNotAllowed(f"Target URL could not be parsed safely: {exc}") from None
    if parts.scheme not in ("http", "https"):
        raise TargetNotAllowed(f"Only http(s) targets are allowed (got scheme {parts.scheme or 'none'!r}).")
    if "@" in parts.netloc:
        raise TargetNotAllowed("Credentials or '@' in the host part are not allowed.")
    if parts.query or parts.fragment:
        raise TargetNotAllowed("Give the base URL only, without a query string or fragment.")
    host = parts.hostname
    if not host:
        raise TargetNotAllowed("Target URL has no host.")
    if not host.isascii():
        raise TargetNotAllowed("Non-ASCII host names are refused (homoglyph risk); use the punycode form.")
    if not (is_loopback_host(host) or _normalize_host(host) in allowed_hosts(extra_allowed)):
        raise TargetNotAllowed(
            f"Refusing to target {host!r}: it is not loopback and not in {ENV_ALLOWLIST}. "
            "Only test builds you own; add a staging host explicitly if that is what you mean."
        )
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a load-test/probe target is loopback or explicitly allow-listed.")
    ap.add_argument("url", help="base URL of the build under test, e.g. http://127.0.0.1:8000")
    ap.add_argument("--allow", action="append", default=[], metavar="HOST", help="extra host you own (repeatable)")
    args = ap.parse_args(argv)
    try:
        print(check_target(args.url, args.allow))
    except TargetNotAllowed as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
