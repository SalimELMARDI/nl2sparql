#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

VENV_LABEL="none"
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  VENV_LABEL="$(basename "$VIRTUAL_ENV")"
elif [[ -n "${CONDA_PREFIX:-}" ]]; then
  VENV_LABEL="$(basename "$CONDA_PREFIX")"
elif [[ -d ".venv" && -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  VENV_LABEL=".venv (auto)"
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN"
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
PROJECT_NAME="$(basename "$SCRIPT_DIR")"

USE_COLOR=false
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  USE_COLOR=true
fi

COLOR_RESET=""
COLOR_DIM=""
COLOR_ACCENT=""
if $USE_COLOR; then
  COLOR_RESET=$'\033[0m'
  COLOR_DIM=$'\033[90m'
  COLOR_ACCENT=$'\033[1;36m'
fi

accent() {
  printf '%s%s%s' "$COLOR_ACCENT" "$*" "$COLOR_RESET"
}

dim() {
  printf '%s%s%s' "$COLOR_DIM" "$*" "$COLOR_RESET"
}

GRADIENT_CODES=("1;38;5;25" "1;38;5;27" "1;38;5;33" "1;38;5;39" "1;38;5;45" "1;38;5;81")

gradient_line() {
  local line="$1"
  local newline="${2:-1}"
  local width="${#line}"
  local denom=$((width > 1 ? width - 1 : 1))
  local i ch idx color

  for ((i=0; i<width; i++)); do
    ch="${line:i:1}"
    if [[ "$ch" == " " ]]; then
      printf " "
      continue
    fi
    idx=$(( i * (${#GRADIENT_CODES[@]} - 1) / denom ))
    color="${GRADIENT_CODES[$idx]}"
    if $USE_COLOR; then
      printf '\033[%sm%s\033[0m' "$color" "$ch"
    else
      printf '%s' "$ch"
    fi
  done
  if (( newline == 1 )); then
    printf '\n'
  fi
}

gradient_3d_line() {
  local line="$1"
  local newline="${2:-1}"
  local width="${#line}"
  local denom=$((width > 1 ? width - 1 : 1))
  local shadow=""
  local i ch idx color

  for ((i=0; i<width+1; i++)); do
    shadow+=" "
  done

  for ((i=0; i<width; i++)); do
    ch="${line:i:1}"
    if [[ "$ch" != " " ]]; then
      shadow="${shadow:0:$((i+1))}░${shadow:$((i+2))}"
    fi
  done

  for ((i=0; i<width; i++)); do
    ch="${line:i:1}"
    if [[ "$ch" != " " ]]; then
      idx=$(( i * (${#GRADIENT_CODES[@]} - 1) / denom ))
      color="${GRADIENT_CODES[$idx]}"
      if $USE_COLOR; then
        printf '\033[%sm%s\033[0m' "$color" "$ch"
      else
        printf '%s' "$ch"
      fi
    else
      if [[ "${shadow:i:1}" == "░" ]]; then
        if $USE_COLOR; then
          printf '\033[90m░\033[0m'
        else
          printf '░'
        fi
      else
        printf ' '
      fi
    fi
  done
  if (( newline == 1 )); then
    printf '\n'
  fi
}

ARROW_LINES=(
  "██   "
  " ███ "
  "  ███"
  " ███ "
  "██   "
)

LOGO_TEXT_LINES=(
  "█   █ █     █████ █████ █████ █████ █████ █████ █"
  "██  █ █         █ █     █   █ █   █ █   █ █   █ █"
  "█ █ █ █     █████ █████ █████ █████ █████ █   █ █"
  "█  ██ █     █         █ █     █   █ █  █  █  ██ █"
  "█   █ █████ █████ █████ █     █   █ █   █ █████ █████"
)

LOGO_LINES=()
for idx in "${!LOGO_TEXT_LINES[@]}"; do
  LOGO_LINES+=("${ARROW_LINES[$idx]}  ${LOGO_TEXT_LINES[$idx]}")
done

repeat_char() {
  local char="$1"
  local count="$2"
  local out=""
  for ((i=0; i<count; i++)); do
    out+="$char"
  done
  printf '%s' "$out"
}

ARROW_GAP=2
max_len=0
for idx in "${!LOGO_TEXT_LINES[@]}"; do
  arrow_len=${#ARROW_LINES[$idx]}
  text_len=${#LOGO_TEXT_LINES[$idx]}
  line_len=$((arrow_len + ARROW_GAP + text_len))
  (( line_len > max_len )) && max_len=$line_len
done

for idx in "${!LOGO_TEXT_LINES[@]}"; do
  arrow_line="${ARROW_LINES[$idx]}"
  text_line="${LOGO_TEXT_LINES[$idx]}"
  if $USE_COLOR; then
    gradient_line "$arrow_line" 0
    printf '%*s' "$ARROW_GAP" ""
    gradient_3d_line "$text_line" 1
  else
    echo "${arrow_line}$(repeat_char " " "$ARROW_GAP")${text_line}"
  fi
done

echo
echo "$(accent "Tips for getting started:")"
echo "1. Ask questions about DBpedia entities."
echo "2. Be specific (time, place, type) for better accuracy."
echo "3. Type 'exit' or 'quit' to stop."

read_question() {
  local placeholder="Type your question"
  local first=""
  local rest=""

  if [[ ! -t 0 ]]; then
    IFS= read -r QUESTION || return 1
    return 0
  fi

  if $USE_COLOR; then
    printf '%s> %s%s' "$COLOR_ACCENT" "$COLOR_RESET" "$(dim "$placeholder")"
  else
    printf '> %s' "$placeholder"
  fi

  if ! IFS= read -r -n 1 -s first; then
    printf '\n'
    return 1
  fi

  case "$first" in
    $'\r'|$'\n')
      printf '\n'
      QUESTION=""
      return 0
      ;;
    $'\x03')
      printf '\n'
      exit 130
      ;;
    $'\x04')
      printf '\n'
      return 1
      ;;
  esac

  printf '\r\033[K'
  if $USE_COLOR; then
    printf '%s> %s' "$COLOR_ACCENT" "$COLOR_RESET"
  else
    printf '> '
  fi
  printf '%s' "$first"

  if ! IFS= read -r rest; then
    printf '\n'
    return 1
  fi
  QUESTION="${first}${rest}"
  return 0
}

export NL2SPARQL_NO_BANNER=1

while true; do
  echo
  if ! read_question; then
    echo
    break
  fi

  if [[ -z "$QUESTION" ]]; then
    continue
  fi
  if [[ "${QUESTION,,}" == "exit" || "${QUESTION,,}" == "quit" ]]; then
    break
  fi

  "$PYTHON_BIN" main.py --question "$QUESTION"
done
