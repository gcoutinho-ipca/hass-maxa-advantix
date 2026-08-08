#!/usr/bin/env python3
"""Check that every YAML file parses, and that blueprint inputs resolve.

Home Assistant's own `hassfest` does not look at blueprints, and a blueprint with
a typo in an `!input` name fails at import time on the user's machine rather than
in CI. This script closes that gap: it parses every YAML file in the repository
and, for blueprints, cross-checks the declared inputs against the ones actually
referenced, including inputs nested inside collapsible sections.

Run from the repository root:

    python scripts/check_yaml.py
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent

#: sentinel wrapper so `!input foo` survives parsing and can be counted
INPUT_KEY = "__blueprint_input__"

# Home Assistant's custom tags are taught to `SafeLoader` itself, rather than to a
# subclass passed to `yaml.load`. Both are equally safe, but `yaml.safe_load` is
# unambiguously safe to every reader and every static analyser, and a security
# scanner flagging `yaml.load` in a repository that people are deciding whether to
# trust is a conversation worth avoiding.
yaml.SafeLoader.add_constructor(
    "!input", lambda loader, node: {INPUT_KEY: loader.construct_scalar(node)}
)
yaml.SafeLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
yaml.SafeLoader.add_constructor("!include", lambda loader, node: loader.construct_scalar(node))


def declared_inputs(blueprint: dict[str, Any]) -> set[str]:
    """Names of every declared input, flattening collapsible sections."""
    names: set[str] = set()
    for key, value in (blueprint.get("input") or {}).items():
        if isinstance(value, dict) and "input" in value:
            names.update(value["input"] or {})  # a section, not an input
        else:
            names.add(key)
    return names


def referenced_inputs(node: Any) -> set[str]:
    """Every input name reached by an `!input` tag anywhere in the document."""
    if isinstance(node, dict):
        if set(node) == {INPUT_KEY}:
            return {node[INPUT_KEY]}
        return set().union(*(referenced_inputs(v) for v in node.values())) if node else set()
    if isinstance(node, list):
        return set().union(*(referenced_inputs(v) for v in node)) if node else set()
    return set()


def main() -> int:
    """Return 0 when everything parses and every input resolves."""
    failures = 0
    checked = 0

    for path in sorted(REPO.rglob("*.yaml")) + sorted(REPO.rglob("*.yml")):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(REPO)
        try:
            document = yaml.safe_load(path.read_text())
        except yaml.YAMLError as err:
            print(f"FAIL {relative}: does not parse: {err}")
            failures += 1
            continue
        checked += 1

        if not isinstance(document, dict) or "blueprint" not in document:
            continue

        declared = declared_inputs(document["blueprint"])
        referenced = referenced_inputs({k: v for k, v in document.items() if k != "blueprint"})
        missing = referenced - declared
        unused = declared - referenced
        if missing:
            print(f"FAIL {relative}: !input without a declaration: {sorted(missing)}")
            failures += 1
        if unused:
            # Not fatal, but almost always a leftover from an edit.
            print(f"WARN {relative}: declared but never used: {sorted(unused)}")
        if not missing:
            print(f"ok   {relative}: {len(declared)} inputs")

    print(f"\n{checked} YAML file(s) parsed, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
