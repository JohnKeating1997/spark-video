#!/usr/bin/env bash
# scripts/doctor.sh — verify spark-video runtime dependencies.
#
# Usage:
#   ./scripts/doctor.sh
#   ./scripts/doctor.sh --full
#   ./scripts/doctor.sh --quick --json [--narration]
#   ./scripts/doctor.sh --install-plan --json [--narration]
#
# Exit 0 = ready, 1 = something required is missing or wrong.

set -u

mode="full"
json=false
require_bl=false

usage() {
  cat <<'USAGE'
spark-video doctor

Usage:
  doctor.sh [--full] [--json] [--narration]
  doctor.sh --quick [--json] [--narration]
  doctor.sh --install-plan [--json] [--narration]

Modes:
  --quick         Fast readiness check for agents. Avoids version banners.
  --full          Human-readable dependency report. This is the default.
  --install-plan  Print commands that would repair missing dependencies.
  --json          Emit one JSON object and no human prose.
  --narration     Require optional bl + authentication for narration TTS.
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
    --narration)
      require_bl=true
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
missing_wan=false
missing_wan_auth=false
missing_ffmpeg=false
missing_uv=false
missing_python=false
missing_script_bl=false
missing_stage_refs=false
missing_shanyin=false
wan_site="intl"
wan_site_source="default"
videogen_region=""
wan_video_model=""
selected_provider="wan-cli"

json_escape() {
  local s="${1-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

read_workspace_env_value() {
  local key="$1"
  local env_file="$(pwd -P)/.env"
  [ -f "$env_file" ] || return 0
  awk -v key="$key" '
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
      value = $0
      sub("^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=[[:space:]]*", "", value)
      sub(/[[:space:]]+#.*$/, "", value)
      gsub(/^[\047\"]|[\047\"]$/, "", value)
      print value
      exit
    }
  ' "$env_file"
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

detect_wan_package_manager() {
  printf 'npm'
}

run_checks() {
  local check_mode="$1"
  local wan_required="false"

  selected_provider="${SPARK_VIDEO_PROVIDER-${VIDEOGEN_VIDEO_PROVIDER-}}"
  if [ -z "$selected_provider" ]; then
    selected_provider="$(read_workspace_env_value VIDEOGEN_VIDEO_PROVIDER)"
  fi
  selected_provider="${selected_provider:-wan-cli}"
  case "$selected_provider" in
    wan|wan_cli) selected_provider="wan-cli" ;;
    happyhorse) selected_provider="bl" ;;
    seedance) selected_provider="seedance2" ;;
  esac
  if [ "$selected_provider" = "wan-cli" ]; then
    wan_required="true"
  fi
  if [ "$selected_provider" = "bl" ]; then
    require_bl=true
  fi

  if [ "$json" = false ] && [ "$mode" != "install-plan" ]; then
    if [ "$check_mode" = "quick" ]; then
      echo "spark-video doctor (quick)"
    else
      echo "spark-video doctor"
    fi
    echo "=================="
  fi

  section "[wan CLI]"
  if command -v wan >/dev/null 2>&1; then
    if [ "$check_mode" = "full" ]; then
      local wan_ver
      wan_ver="$(wan --version 2>&1 | head -1 || echo 'unknown')"
      add_check "wan" "pass" "$wan_required" "wan found ($wan_ver)"
    else
      add_check "wan" "pass" "$wan_required" "wan found"
    fi

    local wan_config_output parsed_site
    wan_config_output="$(wan config show --output json 2>/dev/null || true)"
    parsed_site="$(printf '%s\n' "$wan_config_output" | sed -nE 's/.*"site"[[:space:]]*:[[:space:]]*"(cn|intl)".*/\1/p' | head -1)"
    if [ "$parsed_site" = "cn" ] || [ "$parsed_site" = "intl" ]; then
      wan_site="$parsed_site"
      wan_site_source="config"
    fi

    if wan auth status --output json >/dev/null 2>&1; then
      add_check "wan-auth" "pass" "$wan_required" "wan auth OK"
    else
      missing_wan_auth=true
      add_check "wan-auth" "$([ "$wan_required" = true ] && echo fail || echo warn)" "$wan_required" "wan auth NOT logged in" \
        "Run: wan auth login --site $wan_site --output json"
    fi
  else
    missing_wan=true
    add_check "wan" "$([ "$wan_required" = true ] && echo fail || echo warn)" "$wan_required" "wan not found" \
      "Install @wan-ai/cli, then run wan auth login --site intl --output json"
  fi

  section "[runtime profile]"
  add_check "video-provider" "pass" "true" "selected video provider: $selected_provider"
  if [ "$wan_site_source" = "config" ]; then
    add_check "wan-site" "pass" "true" "wan account site: $wan_site"
  else
    add_check "wan-site" "warn" "false" "wan account site: intl (default; current site was not recognized)"
  fi

  videogen_region="${VIDEOGEN_REGION-}"
  if [ -z "$videogen_region" ]; then
    videogen_region="$(read_workspace_env_value VIDEOGEN_REGION)"
  fi
  videogen_region="${videogen_region:-beijing}"
  add_check "videogen-region" "info" "false" "DashScope region: $videogen_region"

  wan_video_model="${SPARK_VIDEO_WAN_VIDEO_MODEL-${VIDEOGEN_WAN_VIDEO_MODEL-}}"
  if [ -z "$wan_video_model" ]; then
    wan_video_model="$(read_workspace_env_value VIDEOGEN_WAN_VIDEO_MODEL)"
  fi
  wan_video_model="${wan_video_model:-wan3.0}"
  case "$wan_video_model" in
    3.0|3_0|wan3_0) wan_video_model="wan3.0" ;;
    2.7|2_7|wan2_7) wan_video_model="wan2.7" ;;
  esac
  case "$wan_video_model" in
    wan3.0|wan2.7)
      add_check "wan-video-models" "pass" "$wan_required" "spark-video wan-cli models: wan3.0, wan2.7 (selected: $wan_video_model)"
      ;;
    *)
      add_check "wan-video-models" "$([ "$wan_required" = true ] && echo fail || echo warn)" "$wan_required" "unsupported selected wan-cli model: $wan_video_model; available: wan3.0, wan2.7" \
        "Set VIDEOGEN_WAN_VIDEO_MODEL to wan3.0 or wan2.7"
      ;;
  esac

  if [ "$selected_provider" = "seedance2" ]; then
    local ark_key="${ARK_API_KEY-${VOLCENGINE_API_KEY-}}"
    [ -n "$ark_key" ] || ark_key="$(read_workspace_env_value ARK_API_KEY)"
    if [ -n "$ark_key" ]; then
      add_check "ark-key" "pass" "true" "Ark key configured for seedance2"
    else
      add_check "ark-key" "fail" "true" "ARK_API_KEY missing for seedance2" "Set ARK_API_KEY in the workspace .env"
    fi
  fi

  section "[bl CLI — required for bl rendering or narration]"
  local bl_required="false"
  if [ "$require_bl" = true ] || [ "$selected_provider" = "bl" ]; then
    bl_required="true"
  fi
  if command -v bl >/dev/null 2>&1; then
    if [ "$check_mode" = "full" ]; then
      local bl_ver
      bl_ver="$(bl --version 2>&1 | head -1 || echo 'unknown')"
      add_check "bl" "pass" "$bl_required" "bl found ($bl_ver)"
    else
      add_check "bl" "pass" "$bl_required" "bl found"
    fi
    if bl auth status >/dev/null 2>&1; then
      add_check "bl-auth" "pass" "$bl_required" "bl auth OK"
    else
      missing_bl_auth=true
      if [ "$bl_required" = true ]; then
        add_check "bl-auth" "fail" "true" "bl auth NOT logged in; selected workflow needs bl" "Run: bl auth login"
      else
        add_check "bl-auth" "warn" "false" "bl auth NOT logged in (optional: bl rendering, narration TTS, and clip review)" "Run: bl auth login"
      fi
    fi
  else
    missing_bl=true
    if [ "$bl_required" = true ]; then
      add_check "bl" "fail" "true" "bl not found; selected workflow needs bl" "Install bailian-cli, then authenticate with bl auth login"
    else
      add_check "bl" "warn" "false" "bl not found (optional: bl rendering, narration TTS, and clip review)" "Install bailian-cli only if those features are needed"
    fi
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

  section "[scripts/bl wrapper — optional]"
  if [ -x "$self_dir/bl" ]; then
    add_check "scripts-bl" "pass" "$bl_required" "scripts/bl is executable"
  else
    missing_script_bl=true
    if [ "$require_bl" = true ]; then
      add_check "scripts-bl" "fail" "true" "scripts/bl missing or not executable" "Run: chmod +x $self_dir/bl"
    else
      add_check "scripts-bl" "warn" "false" "scripts/bl missing or not executable (optional)" "Run: chmod +x $self_dir/bl"
    fi
  fi

  section "[python]"
  local uv_python="" pyver=""
  if command -v uv >/dev/null 2>&1; then
    # Scripts run through uv and declare requires-python >=3.10. The shell's
    # python3 may legitimately be Apple's 3.9 even when uv has a suitable
    # managed or Homebrew runtime, so inspect uv's resolver instead of PATH.
    uv_python="$(uv python find '>=3.10' 2>/dev/null || true)"
  fi
  if [ -n "$uv_python" ] && [ -x "$uv_python" ]; then
    pyver="$("$uv_python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
    add_check "python3" "pass" "true" "uv Python runtime found ($pyver)"
  else
    missing_python=true
    add_check "python3" "fail" "true" "uv could not resolve Python 3.10+" "Run: uv python install 3.12"
  fi

  section "[shanyin craft references — optional]"
  local sh_sw_dir="$sh_root/screenwriting-master"
  local sh_dir_dir="$sh_root/director-master"
  if compgen -G "$sh_sw_dir/*.skill" >/dev/null; then
    add_check "shanyin-screenwriting-master" "pass" "false" "shanyin-screenwriting-master present ($sh_root)"
  else
    missing_shanyin=true
    add_check "shanyin-screenwriting-master" "warn" "false" "not installed at $sh_root (optional)" "Run: $self_dir/install-deps.sh"
  fi
  if compgen -G "$sh_dir_dir/*.skill" >/dev/null; then
    add_check "shanyin-director-master" "pass" "false" "shanyin-director-master present ($sh_root)"
  else
    missing_shanyin=true
    add_check "shanyin-director-master" "warn" "false" "not installed at $sh_root (optional)" "Run: $self_dir/install-deps.sh"
  fi

  section "[stage references]"
  local s f
  for s in screenwriter director cast vfx-review clip-review; do
    if [ "$s" = "clip-review" ]; then
      f="$repo_root/references/spark-video-clip-review/instructions.md"
    else
      f="$repo_root/references/spark-video-$s.md"
    fi
    if [ -f "$f" ]; then
      add_check "spark-video-$s" "pass" "true" "spark-video-$s instructions present"
    else
      missing_stage_refs=true
      add_check "spark-video-$s" "fail" "true" "spark-video-$s instructions MISSING" "Reinstall spark-video from a complete skill package"
    fi
  done
}

build_install_plan() {
  local os_name pm wan_pm
  os_name="$(detect_os)"
  pm="$(detect_package_manager)"
  wan_pm="$(detect_wan_package_manager)"

  if [ "$missing_wan" = true ] && [ "$selected_provider" = "wan-cli" ]; then
    add_action "wan" "true" "wan-cli is the default image and video provider" \
      "$wan_pm install --global @wan-ai/cli@latest" \
      "wan auth login --site intl --output json"
  fi

  if [ "$missing_wan_auth" = true ] && [ "$selected_provider" = "wan-cli" ]; then
    add_action "wan-auth" "true" "wan-cli is installed but not authenticated" \
      "wan auth login --site $wan_site --output json"
  fi

  if [ "$missing_bl" = true ]; then
    add_action "bl" "$require_bl" "Bailian CLI: required for bl rendering or narration, and available for clip review" \
      "npm install -g bailian-cli" \
      "bl auth login"
  fi

  if [ "$missing_bl_auth" = true ]; then
    add_action "bl-auth" "$require_bl" "bl is installed but not authenticated" \
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
    add_action "python3" "true" "uv needs a Python 3.10+ runtime for the script toolchain" "uv python install 3.12"
  fi

  if [ "$missing_script_bl" = true ]; then
    add_action "scripts-bl" "$require_bl" "spark-video's optional bl wrapper must be executable" \
      "chmod +x \"$self_dir/bl\""
  fi

  if [ "$missing_stage_refs" = true ]; then
    add_action "stage-references" "true" "The installed spark-video package is incomplete" \
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
  if [ "$missing_wan" = true ] && [ "$selected_provider" = "wan-cli" ]; then
    echo "[required] wan-cli"
    echo "  $wan_pm install --global @wan-ai/cli@latest"
    echo "  wan auth login --site intl --output json"
  fi
  if [ "$missing_wan_auth" = true ] && [ "$selected_provider" = "wan-cli" ]; then
    echo "[required] wan auth"
    echo "  wan auth login --site $wan_site --output json"
  fi
  if [ "$missing_bl" = true ]; then
    if [ "$require_bl" = true ]; then
      echo "[required for selected workflow] bl"
    else
      echo "[optional] bl (video rendering, narration TTS, and clip review)"
    fi
    echo "  npm install -g bailian-cli"
    echo "  bl auth login"
  fi
  if [ "$missing_bl_auth" = true ]; then
    if [ "$require_bl" = true ]; then
      echo "[required for selected workflow] bl auth"
    else
      echo "[optional] bl auth"
    fi
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
    echo "[required] uv Python runtime"
    echo "  uv python install 3.12"
  fi
  if [ "$missing_script_bl" = true ]; then
    echo "[optional unless bl rendering or narration] scripts/bl"
    echo "  chmod +x \"$self_dir/bl\""
  fi
  if [ "$missing_stage_refs" = true ]; then
    echo "[required] stage references"
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
