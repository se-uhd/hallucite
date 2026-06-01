#!/usr/bin/env bash
# run.sh -- the single entry point for the hallucite pipeline.
#
# Why this exists: when hallucite is installed as a Claude Code or Codex CLI plugin, only SKILL.md
# and these scripts ship -- no Python and no `hallucinator`. The dev-clone path (`mise run ...`) is
# not available, and the agent's shell often does not have `uv`/`mise`/`python3.12` on PATH even
# when they are installed under ~/.local/bin or Homebrew. Calling the .py scripts with a bare
# `python` then fails in confusing, easy-to-misread ways. This wrapper makes the skill
# self-sufficient: it resolves (or provisions) a Python 3.12 that can `import hallucinator`, then
# execs the requested script with it.
#
# Contract for callers (see SKILL.md "Stop conditions" and the "Preflight" subsection):
#   - On success it is transparent: it runs the script and forwards its exit code.
#   - On any setup failure it prints a line beginning with `HALLUCITE_BOOTSTRAP_FAILED:` to stderr
#     and exits non-zero. That sentinel means NO audit ran -- there is no output to interpret.
#
# Usage:
#   run.sh doctor                 # provision if needed, then print HALLUCITE_OK / fail loud
#   run.sh audit  <pdf|dir> [...] # -> audit_references.py
#   run.sh triage <subcmd> [...]  # -> triage.py
#   run.sh lint   [...]           # -> lint_markdown.py
#   run.sh python [...]           # exec the resolved interpreter (escape hatch)
#
# Environment overrides:
#   HALLUCITE_PYTHON  a python that already has hallucinator (used as-is; never modified)
#   HALLUCITE_VENV    where to create/use the managed venv
#                     (default: ${XDG_CACHE_HOME:-~/.cache}/hallucite/venv)

set -euo pipefail

FAIL="HALLUCITE_BOOTSTRAP_FAILED:"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
VENV="${HALLUCITE_VENV:-${XDG_CACHE_HOME:-$HOME/.cache}/hallucite/venv}"

die() { printf '\n%s %s\n' "$FAIL" "$*" >&2; exit 3; }

# Locate an executable across PATH plus the locations a plugin's non-interactive shell often misses
# (this is exactly why "can't access python/uv/mise" happens even when they are installed).
find_exe() {
  local name="$1" c
  if c="$(command -v "$name" 2>/dev/null)"; then printf '%s\n' "$c"; return 0; fi
  for c in "$HOME/.local/bin/$name" "$HOME/.cargo/bin/$name" \
           "/opt/homebrew/bin/$name" "/usr/local/bin/$name"; do
    [ -x "$c" ] && { printf '%s\n' "$c"; return 0; }
  done
  return 1
}

py_ok() { [ -n "${1:-}" ] && [ -x "$1" ] && "$1" -c 'import hallucinator' >/dev/null 2>&1; }

is_py312() {
  [ -x "${1:-}" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' \
    >/dev/null 2>&1
}

# Echo a path to a Python 3.12 *base* interpreter to build a venv from, or nothing.
# Note: every command substitution that may fail is suffixed `|| true` and assigned on its own
# line, never inside an `if` condition. Under `set -e`, a failing $(...) on an assignment's RHS
# aborts the function even when it is the left operand of `&&` in an `if` -- which silently turned
# "python3.12 not on PATH" into "no usable Python" and skipped the mise fallback entirely.
find_python312() {
  local c base mise
  for c in python3.12 python3 python; do
    base="$(find_exe "$c" 2>/dev/null || true)"
    if is_py312 "$base"; then printf '%s\n' "$base"; return 0; fi
  done
  # mise may have a 3.12 installed even if it is not on PATH; use it but never auto-install via it.
  mise="$(find_exe mise 2>/dev/null || true)"
  if [ -n "$mise" ]; then
    base="$("$mise" where python@3.12 2>/dev/null || true)/bin/python3.12"
    if is_py312 "$base"; then printf '%s\n' "$base"; return 0; fi
  fi
  return 1
}

resolve_python() {
  # 1) explicit override -- used verbatim, never managed.
  if [ -n "${HALLUCITE_PYTHON:-}" ]; then
    py_ok "$HALLUCITE_PYTHON" || die \
      "\$HALLUCITE_PYTHON ($HALLUCITE_PYTHON) cannot 'import hallucinator'. Install it there \
(\"$HALLUCITE_PYTHON\" -m pip install hallucinator) or unset HALLUCITE_PYTHON so run.sh can \
provision its own venv."
    printf '%s\n' "$HALLUCITE_PYTHON"; return 0
  fi
  # 2) the managed venv is already good.
  if py_ok "$VENV/bin/python"; then printf '%s\n' "$VENV/bin/python"; return 0; fi
  # 3) provision the managed venv -- prefer uv (it can also fetch Python 3.12), else stdlib venv.
  mkdir -p "$(dirname -- "$VENV")"
  local uv; uv="$(find_exe uv 2>/dev/null || true)"
  if [ -n "$uv" ]; then
    "$uv" venv -p 3.12 "$VENV" >&2 \
      || die "'uv venv -p 3.12 $VENV' failed (see output above)."
    "$uv" pip install --python "$VENV/bin/python" hallucinator >&2 \
      || die "'uv pip install hallucinator' failed (network? see output above)."
  else
    local py312; py312="$(find_python312 2>/dev/null || true)"
    [ -n "$py312" ] || die \
      "no usable Python found. hallucinator needs Python 3.12 (it ships 3.12 wheels; 3.13 builds \
from source). Install 'uv' (https://docs.astral.sh/uv/) -- which can fetch 3.12 itself -- or \
install Python 3.12, then re-run. To reuse an existing environment instead, set \$HALLUCITE_PYTHON \
to a python that already has hallucinator."
    "$py312" -m venv "$VENV" >&2 || die "'$py312 -m venv $VENV' failed (see output above)."
    "$VENV/bin/python" -m pip install --upgrade pip >&2 || true
    "$VENV/bin/python" -m pip install hallucinator >&2 \
      || die "'pip install hallucinator' into $VENV failed (network? see output above)."
  fi
  py_ok "$VENV/bin/python" \
    || die "provisioned venv at $VENV still cannot 'import hallucinator'."
  printf '%s\n' "$VENV/bin/python"
}

cmd="${1:-}"
case "$cmd" in
  doctor|audit|triage|lint|python) shift ;;
  ""|-h|--help)
    printf 'usage: run.sh {doctor|audit|triage|lint|python} [args...]\n' >&2; exit 2 ;;
  *)
    printf '%s unknown command %q (expected doctor|audit|triage|lint|python)\n' "$FAIL" "$cmd" >&2
    exit 2 ;;
esac

PYTHON="$(resolve_python)"

case "$cmd" in
  doctor)
    ver="$("$PYTHON" -c 'import importlib.metadata as m; print(m.version("hallucinator"))' \
           2>/dev/null || echo '?')"
    printf 'HALLUCITE_OK: %s (hallucinator %s)\n' "$PYTHON" "$ver" ;;
  audit)  exec "$PYTHON" "$SCRIPT_DIR/audit_references.py" "$@" ;;
  triage) exec "$PYTHON" "$SCRIPT_DIR/triage.py" "$@" ;;
  lint)   exec "$PYTHON" "$SCRIPT_DIR/lint_markdown.py" "$@" ;;
  python) exec "$PYTHON" "$@" ;;
esac
