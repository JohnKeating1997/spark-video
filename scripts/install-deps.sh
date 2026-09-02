#!/usr/bin/env bash
# scripts/install-deps.sh — clone optional shanyin craft references.
# Failure is non-fatal: the pipeline runs without them (stage references fall
# back to their baked-in reference.md).

set -u
target_root="${SPARK_VIDEO_SHANYIN_DIR:-$(pwd -P)/.spark-video/references/shanyin}"
mkdir -p "$target_root"
cd "$target_root"

clone_or_pull() {
  local url="$1" target="$2"
  if [ -d "$target/.git" ]; then
    echo "[$target] already cloned — pulling latest"
    (cd "$target" && git pull --ff-only 2>&1 | head -5) || {
      echo "  ⚠ pull failed (continuing)" >&2
    }
  else
    echo "[$target] cloning $url"
    if git clone --depth 1 "$url" "$target" 2>&1 | head -10; then
      echo "  ✓ cloned"
    else
      echo "  ⚠ clone failed — stage instructions will fall back to bundled guidance" >&2
      rm -rf "$target"
    fi
  fi
}

clone_or_pull \
  "https://github.com/Shanyin-ai/shanyin-screenwriting-master.git" \
  "screenwriting-master"

clone_or_pull \
  "https://github.com/Shanyin-ai/shanyin-director-master.git" \
  "director-master"

echo
echo "Done. Verify with: ls $target_root/"
