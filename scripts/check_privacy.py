#!/usr/bin/env python3
"""Fail the build if personal data or a real network address slips into the repo.

A public repository grown out of a private diagnosis is exactly where a leftover
internal IP address, a work email in a commit trailer, or a real hostname ends up.
Those are not vulnerabilities, and no security scanner looks for them, which is
why they survive: nothing is watching.

This script is what watches. It runs in CI on every push and pull request.

    python scripts/check_privacy.py

Rules, and the reasoning behind each:

* **One identity.** The only contact details this project publishes are the
  author's chosen public ones. Anything else that looks like an email address is a
  finding, including one that arrives in a well-meant contribution.
* **Documentation addresses only.** Examples use a plausible home network
  (192.168.x.x). Addresses from other private ranges are almost always someone's
  actual infrastructure copied out of a working setup.
* **No real hostnames.** Machine names from the author's network, and the names of
  organisations, have no business here.

Everything is checked against files tracked by git, so a local scratch file cannot
fail the build, and nothing outside the published tree is read.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

#: The only contact address this project publishes.
ALLOWED_EMAILS = {"gcoutinho@gmail.com"}

#: Documentation networks. Anything else in a private range is suspect.
ALLOWED_ADDRESS_PREFIXES = ("192.168.", "127.0.0.1", "0.0.0.0")

#: Names that must never appear: the author's real name, machine names from the
#: network the integration was developed against, and organisations.
FORBIDDEN_WORDS = (
    "gilberto",
    "cerveira",
    "cmvnc",
    "cm-vncerveira",
    "gfc-dsk",
    "gfc-dell",
    "openclaw",
    "hermes",
    "proxmox",
    "tailscale",
)

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PRIVATE_ADDRESS = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)
#: Same thing with dots turned into underscores, which is how an address survives
#: inside a Home Assistant entity id and gets missed by an ordinary search.
UNDERSCORED_ADDRESS = re.compile(r"\b(?:10|172|192)_\d{1,3}_\d{1,3}_\d{1,3}\b")

#: Binary and generated files there is no point reading as text.
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".pdf", ".woff", ".woff2"}

#: This file necessarily contains the very patterns it looks for.
SKIP_PATHS = {"scripts/check_privacy.py"}


def tracked_files() -> list[pathlib.Path]:
    """Ask git for the files that are actually published."""
    output = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [REPO / name for name in output.split("\0") if name]


def findings_in(path: pathlib.Path, relative: str) -> list[str]:
    """Every rule violated in one file, as human-readable lines."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # not text, nothing to read

    found: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()

        for address in EMAIL.findall(line):
            # `icon@2x.png` and friends look like addresses to a regex.
            if "." not in address.split("@", 1)[1].rstrip(".") or address.endswith(
                (".png", ".jpg", ".svg", ".yaml", ".yml", ".json", ".py", ".md")
            ):
                continue
            if address.lower() not in ALLOWED_EMAILS:
                found.append(f"{relative}:{number}: unexpected email address: {address}")

        for address in PRIVATE_ADDRESS.findall(line):
            if not address.startswith(ALLOWED_ADDRESS_PREFIXES):
                found.append(f"{relative}:{number}: private network address: {address}")

        for address in UNDERSCORED_ADDRESS.findall(line):
            if not address.startswith("192_168_"):
                found.append(f"{relative}:{number}: address with underscores: {address}")

        for word in FORBIDDEN_WORDS:
            if word in lowered:
                found.append(f"{relative}:{number}: forbidden word: {word}")

    return found


def main() -> int:
    """Return 0 when nothing personal is published."""
    findings: list[str] = []
    checked = 0

    for path in tracked_files():
        relative = path.relative_to(REPO).as_posix()
        if relative in SKIP_PATHS or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if not path.is_file():
            continue
        checked += 1
        findings.extend(findings_in(path, relative))

    for finding in findings:
        print(f"FAIL {finding}")

    print(f"\n{checked} tracked file(s) checked, {len(findings)} finding(s)")
    if findings:
        print(
            "\nIf a finding is a false positive, widen the allow lists at the top of "
            "this script rather than deleting the check."
        )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
