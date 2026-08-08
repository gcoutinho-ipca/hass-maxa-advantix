#!/usr/bin/env bash
# Install the integration into the sandbox the way a user gets it, rather than the
# way a developer has it.
#
# HACS downloads the zip asset attached to a release, unpacks it, and drops the
# result in config/custom_components/<domain>/. This does the same thing with curl,
# so what gets tested is the published artefact: if a file is missing from the zip,
# or the manifest version disagrees with the tag, it shows up here rather than in
# somebody's issue.
#
#     ./install-from-github.sh            # latest release
#     ./install-from-github.sh v1.0.0     # a specific tag
#     ./install-from-github.sh main       # the branch, as a tarball
#
# After running it, comment out the bind mount in docker-compose.yml, otherwise the
# working tree keeps shadowing what you just installed.

set -euo pipefail

REPO="gcoutinho-ipca/hass-maxa-advantix"
DOMAIN="maxa_advantix"
REF="${1:-latest}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HERE/ha-config/custom_components/$DOMAIN"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ "$REF" = "main" ]; then
  say "Downloading the main branch as a tarball"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" \
    | tar -xz -C "$WORK" --strip-components=1
  SOURCE="$WORK/custom_components/$DOMAIN"
else
  if [ "$REF" = "latest" ]; then
    say "Looking up the latest release"
    REF=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
      | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)
    [ -n "$REF" ] || { echo "No release found. Try: $0 main" >&2; exit 1; }
  fi
  say "Downloading $REF"
  # The zip asset is what HACS fetches when hacs.json declares zip_release.
  if curl -fsSL -o "$WORK/$DOMAIN.zip" \
      "https://github.com/$REPO/releases/download/$REF/$DOMAIN.zip"; then
    echo "Using the release zip asset, the same file HACS installs."
    mkdir -p "$WORK/unpacked"
    # Python rather than unzip: every machine that runs Home Assistant has one,
    # and plenty of minimal systems do not have the other.
    if command -v unzip >/dev/null 2>&1; then
      ( cd "$WORK/unpacked" && unzip -q "../$DOMAIN.zip" )
    else
      python3 -m zipfile -e "$WORK/$DOMAIN.zip" "$WORK/unpacked"
    fi
    SOURCE="$WORK/unpacked"
  else
    echo "No zip asset on that release; falling back to the source tarball."
    curl -fsSL "https://github.com/$REPO/archive/refs/tags/$REF.tar.gz" \
      | tar -xz -C "$WORK" --strip-components=1
    SOURCE="$WORK/custom_components/$DOMAIN"
  fi
fi

[ -f "$SOURCE/manifest.json" ] || {
  echo "manifest.json not found in the download: $SOURCE" >&2
  exit 1
}

VERSION=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$SOURCE/manifest.json")
say "Installing $DOMAIN $VERSION into the sandbox"
rm -rf "$TARGET"
mkdir -p "$(dirname "$TARGET")"
cp -r "$SOURCE" "$TARGET"

# What a user would end up with, listed so a missing file is obvious.
find "$TARGET" -type f | sed "s|$TARGET|  custom_components/$DOMAIN|" | sort

cat <<EOF

Installed. Two things left:

  1. Comment out the bind mount for custom_components in docker-compose.yml,
     or the working tree will shadow this install.
  2. docker compose restart homeassistant

Then add the integration from the UI, pointing it at host "maxa-sim", port 502.
EOF
