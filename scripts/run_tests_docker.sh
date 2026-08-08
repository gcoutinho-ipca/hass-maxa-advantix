#!/usr/bin/env bash
# Run the full test suite inside the official Home Assistant image.
#
# Why: the tests need Home Assistant and its test fixtures, and installing those on
# a workstation means pinning a Python version and a hundred transitive
# dependencies against whatever else lives there. The official image already has
# the exact Home Assistant the tests should run against, so the only thing missing
# is the fixtures package.
#
#     ./scripts/run_tests_docker.sh                 # everything
#     ./scripts/run_tests_docker.sh tests/test_read_only.py
#     ./scripts/run_tests_docker.sh -k read_only -x
#
# The image is built once and cached, so only the first run pays for the install.
# Nothing is written to the working tree: it is mounted read-only and copied inside.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="maxa-advantix-tests"
BASE="${HA_IMAGE:-ghcr.io/home-assistant/home-assistant:stable}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1 || [ "${REBUILD:-0}" = "1" ]; then
  printf '\n\033[1mBuilding the test image (once)\033[0m\n'
  docker build -t "$IMAGE" -f - "$HERE" <<EOF
FROM $BASE
# The fixtures package brings pytest and Home Assistant's own test helpers. It is
# installed without touching the Home Assistant already in the image, so the tests
# run against the version users actually have.
RUN pip install --no-cache-dir --root-user-action=ignore \
      pytest-homeassistant-custom-component \
 && python -c "import homeassistant.const as c; print('testing against HA', c.__version__)"
WORKDIR /work
EOF
fi

printf '\n\033[1mRunning tests against %s\033[0m\n' "$BASE"
exec docker run --rm \
  -v "$HERE:/src:ro" \
  "$IMAGE" \
  sh -c '
    set -e
    mkdir -p /work
    cp -r /src/custom_components /src/tests /src/pyproject.toml /work/
    cd /work
    exec pytest '"$(printf '%q ' "${@:-tests}")"'
  '
