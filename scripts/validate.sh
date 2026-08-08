#!/usr/bin/env bash
# Run every check the CI runs, locally, using the same official images.
#
#     ./scripts/validate.sh          # everything
#     ./scripts/validate.sh quick    # skip the two container pulls
#
# Why this exists as well as the workflows: a contributor should be able to know
# their change is good before opening a pull request, and a maintainer should be
# able to reproduce a red CI run without pushing commits to find out. Both
# validators here are the same images GitHub Actions uses, so a pass locally means
# a pass there.
#
# Checks, in the order failures are most likely:
#
#   privacy    no unexpected email addresses, private addresses or real hostnames
#   yaml       every YAML parses; every blueprint !input resolves
#   ruff       lint and formatting, the same two commands the lint job runs
#   hassfest   Home Assistant's own integration validator
#   hacs       the HACS validation action, against the published repository
#   tests      the full suite inside the official Home Assistant image
#
# `hacs` checks the *remote* repository rather than the working tree, so it can
# only tell you about what is pushed. That is a property of the action, not a
# mistake here, and it is worth knowing before you spend time confused by it.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

QUICK="${1:-}"
FAILED=()

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
pass() { printf '\033[32m  pass\033[0m  %s\n' "$*"; }
fail() { printf '\033[31m  FAIL\033[0m  %s\n' "$*"; FAILED+=("$1"); }

bold "privacy"
if python3 scripts/check_privacy.py > /tmp/maxa-privacy.log 2>&1; then
  pass "$(tail -1 /tmp/maxa-privacy.log)"
else
  fail "privacy"; tail -20 /tmp/maxa-privacy.log
fi

bold "yaml and blueprints"
if python3 scripts/check_yaml.py > /tmp/maxa-yaml.log 2>&1; then
  pass "$(tail -1 /tmp/maxa-yaml.log)"
else
  fail "yaml"; tail -20 /tmp/maxa-yaml.log
fi

# Run in the official ruff image rather than from a local install, for the same
# reason the other validators run in containers: the version is then the same one
# everywhere, and nobody needs ruff on their machine to check their own change.
# Cache disabled because the working tree is mounted read-only. The version is
# pinned to the one `.github/workflows/validate.yml` installs, so a pass here is
# a pass there; bump both together.
bold "ruff (lint and format, as the CI runs them)"
if docker run --rm -v "$HERE:/io:ro" -w /io ghcr.io/astral-sh/ruff:0.16.2 \
     check --no-cache custom_components tests scripts > /tmp/maxa-ruff.log 2>&1 \
   && docker run --rm -v "$HERE:/io:ro" -w /io ghcr.io/astral-sh/ruff:0.16.2 \
     format --no-cache --check custom_components tests scripts >> /tmp/maxa-ruff.log 2>&1; then
  pass "$(grep -E 'All checks passed|already formatted' /tmp/maxa-ruff.log | tr '\n' ' ')"
else
  fail "ruff"; tail -25 /tmp/maxa-ruff.log
fi

if [ "$QUICK" != "quick" ]; then
  bold "hassfest (Home Assistant's own validator)"
  if docker run --rm -v "$HERE:/github/workspace" \
       ghcr.io/home-assistant/hassfest:latest > /tmp/maxa-hassfest.log 2>&1; then
    # hassfest exits 0 on warnings too, so warnings are surfaced rather than hidden.
    if grep -q '\[WARNING\]' /tmp/maxa-hassfest.log; then
      fail "hassfest"; grep '\[WARNING\]' /tmp/maxa-hassfest.log
    else
      pass "$(grep 'Invalid integrations' /tmp/maxa-hassfest.log), no warnings"
    fi
  else
    fail "hassfest"; tail -25 /tmp/maxa-hassfest.log
  fi

  bold "hacs (validates the pushed repository, not the working tree)"
  if docker run --rm -v "$HERE:/github/workspace" \
       -e INPUT_CATEGORY=integration \
       -e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-gcoutinho-ipca/hass-maxa-advantix}" \
       -e GITHUB_WORKSPACE=/github/workspace \
       -e "INPUT_GITHUB_TOKEN=$(gh auth token 2>/dev/null)" \
       ghcr.io/hacs/action:main > /tmp/maxa-hacs.log 2>&1; then
    pass "$(grep -o 'All ([0-9]*) checks passed' /tmp/maxa-hacs.log | tail -1)"
  else
    fail "hacs"; grep '::ERROR::' /tmp/maxa-hacs.log | tail -10
  fi
fi

bold "tests (inside the official Home Assistant image)"
if ./scripts/run_tests_docker.sh -q --no-header > /tmp/maxa-tests.log 2>&1; then
  pass "$(grep -E '[0-9]+ passed' /tmp/maxa-tests.log | tail -1)"
else
  fail "tests"; grep -E '^(FAILED|ERROR)' /tmp/maxa-tests.log | head -15
fi

bold "summary"
if [ ${#FAILED[@]} -eq 0 ]; then
  printf '\033[32meverything passed\033[0m\n'
  exit 0
fi
printf '\033[31mfailed: %s\033[0m\n' "${FAILED[*]}"
exit 1
