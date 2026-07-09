#!/usr/bin/env bash
# scripts/doctor.sh — verify spark-video runtime dependencies.
#
# Usage:
#   ./scripts/doctor.sh
#   ./scripts/doctor.sh --full
#   ./scripts/doctor.sh --quick --json
#   ./scripts/doctor.sh --install-plan --json
#
# Exit 0 = ready, 1 = something required is missing or wrong.

set -u

mode="full"
json=false

usage() {
  cat <<'USAGE'
spark-video doctor

Usage:
  doctor.sh [--full] [--json]
  doctor.sh --quick [--json]
  doctor.sh --install-plan [--json]

Modes:
  --quick         Fast readiness check for agents. Avoids version banners.
  --full          Human-readable dependency report. This is the default.
  --install-plan  Print commands that would repair missing dependencies.
  --json          Emit one JSON object and no human prose.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --quick)
      mode="quick"
      ;;
    --full)
      mode="full"
      ;;
    --install-plan)
      mode="install-plan"
      ;;
    --json)
      json=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

ok=true
self_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(dirname "$self_dir")"
sh_root="${SPARK_VIDEO_SHANYIN_DIR:-$(pwd -P)/.spark-video/references/shanyin}"

checks_json=()
actions_json=()

missing_bl=false
missing_bl_auth=false
missing_ffmpeg=false
missing_uv=false
missing_python=false
missing_script_bl=false
missing_subskills=false
missing_shanyin=false

json_escape() {
  local s="${1-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

json_array() {
  local first=true
  printf '['
  for item in "$@"; do
    if $first; then
      first=false
    else
      printf ','
    fi
    printf '"%s"' "$(json_escape "$item")"
  done
  printf ']'
}

join_json_objects() {
  local first=true
  printf '['
  for item in "$@"; do
    if $first; then
      first=false
    else
      printf ','
    fi
    printf '%s' "$item"
  done
  printf ']'
}

emit_check_text() {
  if [ "$json" = true ] || [ "$mode" = "install-plan" ]; then
    return
  fi
  local status="$1"
  local message="$2"
  case "$status" in
    pass) printf '  ✓ %s\n' "$message" ;;
    fail) printf '  ✗ %s\n' "$message" ;;
    warn) printf '  ⚠ %s\n' "$message" ;;
    info) printf '  · %s\n' "$message" ;;
  esac
}

section() {
  if [ "$json" = false ] && [ "$mode" != "install-plan" ]; then
    printf '%s\n' "$1"
  fi
}

add_check() {
  local id="$1"
  local status="$2"
  local required="$3"
  local message="$4"
  local fix="${5-}"

  if [ "$status" = "fail" ] && [ "$required" = "true" ]; then
    ok=false
  fi

  checks_json+=("{\"id\":\"$(json_escape "$id")\",\"status\":\"$(json_escape "$status")\",\"required\":$required,\"message\":\"$(json_escape "$message")\",\"fix\":\"$(json_escape "$fix")\"}")
  emit_check_text "$status" "$message"
}

add_action() {
  local id="$1"
  local required="$2"
  local reason="$3"
  shift 3
  actions_json+=("{\"id\":\"$(json_escape "$id")\",\"required\":$required,\"reason\":\"$(json_escape "$reason")\",\"commands\":$(json_array "$@")}")
}

detect_os() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin) printf 'macos' ;;
    Linux) printf 'linux' ;;
    MINGW*|MSYS*|CYGWIN*) printf 'windows' ;;
    *) printf 'unknown' ;;
  esac
}

detect_package_manager() {
  for pm in brew apt-get dnf yum pacman choco; do
    if command -v "$pm" >/dev/null 2>&1; then
      printf '%s' "$pm"
      return
    fi
  done
  printf 'unknown'
}

run_checks() {
  local check_mode="$1"

  if [ "$json" = false ] && [ "$mode" != "install-plan" ]; then
    if [ "$check_mode" = "quick" ]; then
      echo "spark-video doctor (quick)"
    else
      echo "spark-video doctor"
    fi
    echo "=================="
  fi

  section "[bl CLI]"
  if command -v bl >/dev/null 2>&1; then
    if [ "$check_mode" = "full" ]; then
      local bl_ver
      bl_ver="$(bl --version 2>&1 | head -1 || echo 'unknown')"
      add_check "bl" "pass" "true" "bl found ($bl_ver)"
    else
      add_check "bl" "pass" "true" "bl found"
    fi
    if bl auth status >/dev/null 2>&1; then
      add_check "bl-auth" "pass" "true" "bl auth OK"
    else
      missing_bl_auth=true
      add_check "bl-auth" "fail" "true" "bl auth NOT logged in" "Run: bl auth login"
    fi
  else
    missing_bl=true
    add_check "bl" "fail" "true" "bl not found" "Install bailian-cli, then authenticate with bl auth login"
  fi

  section "[ffmpeg]"
  for bin in ffmpeg ffprobe; do
    if command -v "$bin" >/dev/null 2>&1; then
      if [ "$check_mode" = "full" ]; then
        local version_line
        version_line="$("$bin" -version 2>&1 | head -1 | cut -d, -f1)"
        add_check "$bin" "pass" "true" "$bin found ($version_line)"
      else
        add_check "$bin" "pass" "true" "$bin found"
      fi
    else
      missing_ffmpeg=true
      add_check "$bin" "fail" "true" "$bin not found" "Install ffmpeg with your OS package manager"
    fi
  done

  section "[uv]"
  if command -v uv >/dev/null 2>&1; then
    if [ "$check_mode" = "full" ]; then
      add_check "uv" "pass" "true" "uv found ($(uv --version 2>&1))"
    else
      add_check "uv" "pass" "true" "uv found"
    fi
  else
    missing_uv=true
    add_check "uv" "fail" "true" "uv not found" "Install uv"
  fi

  section "[scripts/bl wrapper]"
  if [ -x "$self_dir/bl" ]; then
    add_check "scripts-bl" "pass" "true" "scripts/bl is executable"
  else
    missing_script_bl=true
    add_check "scripts-bl" "fail" "true" "scripts/bl missing or not executable" "Run: chmod +x $self_dir/bl"
  fi

  section "[python]"
  if command -v python3 >/dev/null 2>&1; then
    local pyver py_major py_minor
    pyver="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
    py_major="$(python3 -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo 0)"
    py_minor="$(python3 -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
    if [ "$py_major" -gt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -ge 10 ]; }; then
      add_check "python3" "pass" "true" "python3 found ($pyver)"
    else
      missing_python=true
      add_check "python3" "fail" "true" "python3 too old ($pyver). Need 3.10+" "Install Python 3.10+"
    fi
  else
    missing_python=true
    add_check "python3" "fail" "true" "python3 not found" "Install Python 3.10+"
  fi

  section "[shanyin craft references — optional]"
  local sh_sw="$sh_root/screenwriting-master/SKILL.md"
  local sh_dir="$sh_root/director-master/SKILL.md"
  if [ -f "$sh_sw" ]; then
    add_check "shanyin-screenwriting-master" "pass" "false" "shanyin-screenwriting-master present ($sh_root)"
  else
    missing_shanyin=true
    add_check "shanyin-screenwriting-master" "warn" "false" "not installed at $sh_root (optional)" "Run: $self_dir/install-deps.sh"
  fi
  if [ -f "$sh_dir" ]; then
    add_check "shanyin-director-master" "pass" "false" "shanyin-director-master present ($sh_root)"
  else
    missing_shanyin=true
    add_check "shanyin-director-master" "warn" "false" "not installed at $sh_root (optional)" "Run: $self_dir/install-deps.sh"
  fi

  section "[sub-skills]"
  local s f
  for s in screenwriter director cast vfx-review clip-review producer; do
    f="$repo_root/references/spark-video-$s/SKILL.md"
    if [ -f "$f" ]; then
      add_check "spark-video-$s" "pass" "true" "spark-video-$s SKILL.md present"
    else
      missing_subskills=true
      add_check "spark-video-$s" "fail" "true" "spark-video-$s SKILL.md MISSING" "Reinstall spark-video from a complete skill package"
    fi
  done
}

build_install_plan() {
  local os_name pm
  os_name="$(detect_os)"
  pm="$(detect_package_manager)"

  if [ "$missing_bl" = true ]; then
    add_action "bl" "true" "Aliyun Bailian CLI is required for model calls" \
      "npm install -g bailian-cli" \
      "npx skills add modelstudioai/skills --all -g"
  fi

  if [ "$missing_bl_auth" = true ]; then
    add_action "bl-auth" "true" "bl is installed but not authenticated" \
      "bl auth login"
  fi

  if [ "$missing_ffmpeg" = true ]; then
    case "$pm" in
      brew) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "brew install ffmpeg" ;;
      apt-get) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "sudo apt-get update && sudo apt-get install -y ffmpeg" ;;
      dnf) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "sudo dnf install -y ffmpeg" ;;
      yum) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "sudo yum install -y ffmpeg" ;;
      pacman) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "sudo pacman -S --needed ffmpeg" ;;
      choco) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching" "choco install ffmpeg" ;;
      *) add_action "ffmpeg" "true" "ffmpeg and ffprobe are required for video stitching; no supported package manager was detected" ;;
    esac
  fi

  if [ "$missing_uv" = true ]; then
    case "$pm" in
      brew) add_action "uv" "true" "uv is required to run Python scripts with inline dependencies" "brew install uv" ;;
      *) add_action "uv" "true" "uv is required to run Python scripts with inline dependencies" "curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
    esac
  fi

  if [ "$missing_python" = true ]; then
    case "$pm" in
      brew) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "brew install python" ;;
      apt-get) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "sudo apt-get update && sudo apt-get install -y python3" ;;
      dnf) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "sudo dnf install -y python3" ;;
      yum) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "sudo yum install -y python3" ;;
      pacman) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "sudo pacman -S --needed python" ;;
      choco) add_action "python3" "true" "Python 3.10+ is required by the script toolchain" "choco install python" ;;
      *) add_action "python3" "true" "Python 3.10+ is required by the script toolchain; no supported package manager was detected" ;;
    esac
  fi

  if [ "$missing_script_bl" = true ]; then
    add_action "scripts-bl" "true" "spark-video's bl wrapper must be executable" \
      "chmod +x \"$self_dir/bl\""
  fi

  if [ "$missing_subskills" = true ]; then
    add_action "sub-skills" "true" "The installed spark-video package is incomplete" \
      "npx skills add https://github.com/JohnKeating1997/spark-video --skill spark-video -g -y"
  fi

  if [ "$missing_shanyin" = true ]; then
    add_action "shanyin-references" "false" "Optional Shanyin craft references are not installed" \
      "\"$self_dir/install-deps.sh\""
  fi

  if [ "$json" = true ]; then
    printf '{"ok":%s,"mode":"install-plan","os":"%s","package_manager":"%s","actions":%s}\n' \
      "$ok" "$(json_escape "$os_name")" "$(json_escape "$pm")" "$(join_json_objects "${actions_json[@]}")"
    return
  fi

  if [ "${#actions_json[@]}" -eq 0 ]; then
    echo "No install actions needed."
    return
  fi

  echo "Install plan"
  echo "============"
  echo "Ask the user before running each command."
  echo
  if [ "$missing_bl" = true ]; then
    echo "[required] bl"
    echo "  npm install -g bailian-cli"
    echo "  npx skills add modelstudioai/skills --all -g"
  fi
  if [ "$missing_bl_auth" = true ]; then
    echo "[required] bl auth"
    echo "  bl auth login"
  fi
  if [ "$missing_ffmpeg" = true ]; then
    echo "[required] ffmpeg"
    case "$pm" in
      brew) echo "  brew install ffmpeg" ;;
      apt-get) echo "  sudo apt-get update && sudo apt-get install -y ffmpeg" ;;
      dnf) echo "  sudo dnf install -y ffmpeg" ;;
      yum) echo "  sudo yum install -y ffmpeg" ;;
      pacman) echo "  sudo pacman -S --needed ffmpeg" ;;
      choco) echo "  choco install ffmpeg" ;;
      *) echo "  Install ffmpeg with this OS package manager" ;;
    esac
  fi
  if [ "$missing_uv" = true ]; then
    echo "[required] uv"
    if [ "$pm" = "brew" ]; then
      echo "  brew install uv"
    else
      echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
  fi
  if [ "$missing_python" = true ]; then
    echo "[required] python3"
    case "$pm" in
      brew) echo "  brew install python" ;;
      apt-get) echo "  sudo apt-get update && sudo apt-get install -y python3" ;;
      dnf) echo "  sudo dnf install -y python3" ;;
      yum) echo "  sudo yum install -y python3" ;;
      pacman) echo "  sudo pacman -S --needed python" ;;
      choco) echo "  choco install python" ;;
      *) echo "  Install Python 3.10+ with this OS package manager" ;;
    esac
  fi
  if [ "$missing_script_bl" = true ]; then
    echo "[required] scripts/bl"
    echo "  chmod +x \"$self_dir/bl\""
  fi
  if [ "$missing_subskills" = true ]; then
    echo "[required] sub-skills"
    echo "  Reinstall spark-video from a complete repository or skills package"
  fi
  if [ "$missing_shanyin" = true ]; then
    echo "[optional] Shanyin craft references"
    echo "  \"$self_dir/install-deps.sh\""
  fi
}

check_mode="$mode"
if [ "$mode" = "install-plan" ]; then
  check_mode="quick"
fi

run_checks "$check_mode"

if [ "$mode" = "install-plan" ]; then
  build_install_plan
  if $ok; then
    exit 0
  fi
  exit 1
fi

if [ "$json" = true ]; then
  printf '{"ok":%s,"mode":"%s","skill_dir":"%s","workspace":"%s","shanyin_dir":"%s","checks":%s}\n' \
    "$ok" "$(json_escape "$mode")" "$(json_escape "$repo_root")" "$(json_escape "$(pwd -P)")" "$(json_escape "$sh_root")" "$(join_json_objects "${checks_json[@]}")"
else
  echo
  if $ok; then
    echo "All required checks passed. spark-video is ready."
  else
    echo "Some required checks failed. Run: $self_dir/doctor.sh --install-plan"
  fi
fi

if $ok; then
  exit 0
fi
exit 1
