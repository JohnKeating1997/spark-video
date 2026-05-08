#!/usr/bin/env bash
# Install / refresh the Shanyin upstream skills used as our craft layer.
#
# We *wrap* these skills: our own SKILL.md files (under .claude/skills/) load
# them via the references/ folder. The Shanyin trees are the single source of
# truth for narrative + directing methodology; our own SKILL.md only contains
# the videogen-specific contract (CLI commands, file paths, schema).
#
# Idempotent. Safe to re-run to refresh from upstream main.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SW_REPO="https://github.com/Shanyin-ai/shanyin-screenwriting-master.git"
DR_REPO="https://github.com/Shanyin-ai/shanyin-director-master.git"

SW_DEST="$ROOT/.claude/skills/screenwriter/references/shanyin-screenwriting"
DR_DEST="$ROOT/.claude/skills/video-director/references/shanyin-director"

echo "→ cloning $SW_REPO"
git clone --depth 1 "$SW_REPO" "$TMP/sw" >/dev/null 2>&1
echo "→ cloning $DR_REPO"
git clone --depth 1 "$DR_REPO" "$TMP/dr" >/dev/null 2>&1

# Screenwriter ships only the .skill (zip). Extract it.
SW_SKILL_ZIP="$(find "$TMP/sw" -maxdepth 2 -name '*.skill' -print -quit)"
if [[ -z "${SW_SKILL_ZIP:-}" ]]; then
  echo "screenwriting-master: .skill archive not found in upstream" >&2
  exit 1
fi
mkdir -p "$TMP/sw-extract"
unzip -q -o "$SW_SKILL_ZIP" -d "$TMP/sw-extract"
SW_SRC="$(find "$TMP/sw-extract" -maxdepth 2 -name SKILL.md -print -quit)"
SW_SRC="$(dirname "$SW_SRC")"

# Director ships an unpacked folder alongside the .skill — prefer the folder.
DR_SRC="$TMP/dr/director-master"
if [[ ! -f "$DR_SRC/SKILL.md" ]]; then
  echo "director-master: SKILL.md not found in upstream folder" >&2
  exit 1
fi

rm -rf "$SW_DEST" "$DR_DEST"
mkdir -p "$(dirname "$SW_DEST")" "$(dirname "$DR_DEST")"
cp -R "$SW_SRC" "$SW_DEST"
cp -R "$DR_SRC" "$DR_DEST"

# Stamp the install metadata so the wrapper SKILL.md can call out the version.
SW_SHA="$(git -C "$TMP/sw" rev-parse HEAD)"
DR_SHA="$(git -C "$TMP/dr" rev-parse HEAD)"
cat > "$SW_DEST/INSTALL.md" <<EOF
Installed from $SW_REPO @ $SW_SHA on $(date -u +%Y-%m-%dT%H:%M:%SZ)
Refresh: bash scripts/install-shanyin-skills.sh
EOF
cat > "$DR_DEST/INSTALL.md" <<EOF
Installed from $DR_REPO @ $DR_SHA on $(date -u +%Y-%m-%dT%H:%M:%SZ)
Refresh: bash scripts/install-shanyin-skills.sh
EOF

echo "✓ screenwriter ← $SW_REPO  ($SW_SHA)"
echo "  $SW_DEST"
echo "✓ director     ← $DR_REPO  ($DR_SHA)"
echo "  $DR_DEST"
