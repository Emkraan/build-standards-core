#!/usr/bin/env bash
# preflight.sh - run what CI will run, locally, before a push (github-repo-standard 8c).
#
#   scripts/preflight.sh                      lint what this branch changed against origin/main
#   scripts/preflight.sh --all                lint everything regardless of the diff
#   scripts/preflight.sh --body-file FILE     also lint the PR body issue declaration
#   scripts/preflight.sh --pre-push           hook mode (quiet when nothing relevant changed)
#
# Runs EXACTLY the CI ruff commands (`ruff check .` then `ruff format --check .`) at the ruff
# version CI pins: the pin is read from the CI workflow below, so it can never drift from CI.
# Ruff comes from `uvx ruff@<pin>` (no global install); a PATH ruff is used only if it is that
# exact version. Ruff runs only when a .py file (or ruff config) changed. No browser is ever
# started (operating contract section 10). Exit 0 = pass, non-zero = fail.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

# ---- per-repo configuration -------------------------------------------------------------
RUFF_SRC=".github/workflows/checks.yml" # the CI file that carries the literal ruff==X.Y.Z
RUFF_DIRS=(.)                             # directories CI runs ruff in (relative to repo root)
extra_checks() { :; }                     # repo-specific CI steps; call run_step "name" cmd...
# ------------------------------------------------------------------------------------------

MODE=manual
ALL=0
BODY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pre-push) MODE=hook ;;
    --all) ALL=1 ;;
    --body-file) BODY="${2:-}"; shift ;;
    -h | --help) sed -n 2,14p "$0"; exit 0 ;;
    *) echo "preflight: unknown argument $1" >&2; exit 2 ;;
  esac
  shift
done

FAILS=()
RAN=0
run_step() { # run_step <label> <command...>
  local label=$1
  shift
  RAN=1
  if "$@"; then echo "preflight: ok    $label"; else echo "preflight: FAIL  $label"; FAILS+=("$label"); fi
}

# Files this branch changes: committed (vs the merge base with origin/main) plus tracked edits.
base=""
for ref in origin/main origin/master main; do
  git rev-parse -q --verify "$ref" >/dev/null && base=$(git merge-base HEAD "$ref" 2>/dev/null) && break
done
changed_files() {
  if [ "$ALL" -eq 1 ] || [ -z "$base" ]; then git ls-files; return; fi
  { git diff --name-only "$base" HEAD; git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u
}
CHANGED=$(changed_files)
changed_match() { printf '%s\n' "$CHANGED" | grep -Eq "$1"; }

# ---- ruff -------------------------------------------------------------------------------
ruff_pin() {
  local pins
  pins=$(grep -ohE 'ruff==[0-9]+\.[0-9]+\.[0-9]+' "$RUFF_SRC" 2>/dev/null | sort -u)
  [ -n "$pins" ] && [ "$(printf '%s\n' "$pins" | wc -l)" -eq 1 ] || return 1
  printf '%s\n' "${pins#ruff==}"
}

ruff_cmd() { # prints the command prefix for the pinned ruff
  local pin=$1
  if command -v uvx >/dev/null 2>&1; then
    echo "uvx --quiet ruff@$pin"
  elif command -v ruff >/dev/null 2>&1 && [ "$(ruff --version | awk '{print $2}')" = "$pin" ]; then
    echo "ruff"
  else
    return 1
  fi
}

ruff_dir() { # ruff_dir <dir> <prefix>
  local dir=$1 prefix=$2
  (
    cd "$dir" || exit 2
    $prefix check . && $prefix format --check .
  )
}

run_ruff() {
  local pin prefix dir pattern
  pin=$(ruff_pin) || { echo "preflight: FAIL  ruff pin: $RUFF_SRC must carry exactly one ruff==X.Y.Z"; FAILS+=("ruff pin"); RAN=1; return; }
  prefix=$(ruff_cmd "$pin") || {
    echo "preflight: FAIL  ruff $pin unavailable: install uv (https://docs.astral.sh/uv/) so uvx can fetch it"
    FAILS+=("ruff unavailable"); RAN=1; return
  }
  for dir in "${RUFF_DIRS[@]}"; do
    if [ "$dir" = . ]; then pattern='\.py$|(^|/)(pyproject|ruff|\.ruff)\.toml$'; else pattern="^${dir}/.*(\.py|pyproject\.toml|ruff\.toml)$"; fi
    if [ "$ALL" -eq 1 ] || changed_match "$pattern"; then
      run_step "ruff $pin check + format --check ($dir)" ruff_dir "$dir" "$prefix"
    fi
  done
}

run_ruff
extra_checks

# ---- PR body issue declaration -----------------------------------------------------------
if [ -n "$BODY" ]; then
  # This repo carries the CI check itself (core-ci.py pr-issue), so the body is linted with it.
  if [ ! -f "$BODY" ]; then
    echo "preflight: FAIL  PR body file not found: $BODY"; FAILS+=("pr body"); RAN=1
  else
    run_step "PR body issue declaration" env PR_BODY="$(cat "$BODY")" PR_TITLE="preflight" PR_AUTHOR="preflight" \
      PR_BRANCH="preflight" GITHUB_REPOSITORY="" python3 -I templates/overlay/scripts/core-ci.py pr-issue
  fi
elif [ "$MODE" = manual ]; then
  echo "preflight: note  no --body-file given; lint the PR body with: scripts/preflight.sh --body-file <file>"
fi

if [ "${#FAILS[@]}" -gt 0 ]; then
  echo "preflight: FAIL (${FAILS[*]}). Fix, then push again."
  exit 1
fi
[ "$RAN" -eq 1 ] || { [ "$MODE" = hook ] || echo "preflight: nothing to check in this diff"; }
[ "$RAN" -eq 1 ] && echo "preflight: PASS"
exit 0
