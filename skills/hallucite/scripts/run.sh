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
#   run.sh check-env              # provision if needed, then print HALLUCITE_OK / fail loud
#   run.sh upgrade                # upgrade hallucinator in the managed venv
#   run.sh audit  <pdf|dir> [...] # -> audit_references.py
#   run.sh triage <subcmd> [...]  # -> triage.py
#   run.sh lint   [...]           # -> lint_markdown.py
#   run.sh python [...]           # exec the resolved interpreter (escape hatch)
#
# Why `upgrade` exists: `resolve_python` reuses the managed venv as soon as it can import
# hallucinator, so the unpinned `pip install hallucinator` below runs only when that venv is first
# created. With no explicit upgrade path the venv silently stays on whatever version was current
# the day it was built, for the life of the install, and audits keep running on stale verification
# logic with nothing to show for it. `check-env` warns when a newer release exists.
#
# Environment overrides:
#   HALLUCITE_PYTHON  a python that already has hallucinator (used as-is; never modified)
#   HALLUCITE_VENV    where to create/use the managed venv
#                     (default: ${XDG_CACHE_HOME:-~/.cache}/hallucite/venv)
#   HALLUCITE_NO_VERSION_CHECK  set to any value to skip check-env's PyPI lookup (offline/CI)

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

hallucinator_version() {
  "$1" -c 'import importlib.metadata as m; print(m.version("hallucinator"))' 2>/dev/null \
    || echo '?'
}

# The newest hallucinator on PyPI, or nothing if the lookup is skipped, offline, or slow. Never
# fatal: a version check must not be able to block an audit.
pypi_latest() {
  [ -n "${HALLUCITE_NO_VERSION_CHECK:-}" ] && return 0
  local curl; curl="$(find_exe curl 2>/dev/null || true)"
  [ -n "$curl" ] || return 0
  "$curl" -fsS --max-time 3 https://pypi.org/pypi/hallucinator/json 2>/dev/null \
    | "$1" -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null \
    || true
}

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
  check-env|upgrade|audit|triage|lint|python) shift ;;
  ""|-h|--help)
    printf 'usage: run.sh {check-env|upgrade|audit|triage|lint|python} [args...]\n' >&2; exit 2 ;;
  *)
    printf '%s unknown command %q (expected check-env|upgrade|audit|triage|lint|python)\n' \
      "$FAIL" "$cmd" >&2
    exit 2 ;;
esac

PYTHON="$(resolve_python)"

# The pipeline scripts shell out to pdftotext (poppler), which subprocess resolves via PATH alone.
# Append the same fallback dirs find_exe searches, so a plugin shell that misses Homebrew or
# ~/.local/bin on PATH still resolves it -- and the check-env probe below sees what the audit sees.
for d in "$HOME/.local/bin" "$HOME/.cargo/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
  if [ -d "$d" ]; then
    case ":$PATH:" in *":$d:"*) ;; *) PATH="$PATH:$d" ;; esac
  fi
done
export PATH

case "$cmd" in
  check-env)
    ver="$(hallucinator_version "$PYTHON")"
    printf 'HALLUCITE_OK: %s (hallucinator %s)\n' "$PYTHON" "$ver"
    # Non-fatal: the audit's extraction step needs pdftotext; warn now rather than failing later.
    find_exe pdftotext >/dev/null \
      || printf 'warning: pdftotext (poppler) not found; the audit needs it for PDF text extraction (e.g. brew install poppler).\n' >&2
    # Non-fatal: the managed venv never upgrades itself, so say so when it has fallen behind.
    # `sort -V` rather than string compare, so a locally-built newer version is not called stale.
    latest="$(pypi_latest "$PYTHON")"
    if [ -n "$latest" ] && [ "$latest" != "$ver" ] \
       && [ "$(printf '%s\n%s\n' "$ver" "$latest" | sort -V | tail -n 1)" = "$latest" ]; then
      printf 'warning: hallucinator %s is installed but %s is available; run `run.sh upgrade` (the managed venv does not update itself).\n' \
        "$ver" "$latest" >&2
    fi ;;
  upgrade)
    if [ -n "${HALLUCITE_PYTHON:-}" ]; then
      die "\$HALLUCITE_PYTHON is set ($HALLUCITE_PYTHON); run.sh never modifies an interpreter it \
does not manage. Upgrade it yourself (\"$HALLUCITE_PYTHON\" -m pip install --upgrade hallucinator) \
or unset HALLUCITE_PYTHON to use the managed venv."
    fi
    before="$(hallucinator_version "$PYTHON")"
    uv="$(find_exe uv 2>/dev/null || true)"
    if [ -n "$uv" ]; then
      "$uv" pip install --python "$PYTHON" --upgrade hallucinator >&2 \
        || die "'uv pip install --upgrade hallucinator' failed (network? see output above)."
    else
      "$PYTHON" -m pip install --upgrade hallucinator >&2 \
        || die "'pip install --upgrade hallucinator' failed (network? see output above)."
    fi
    py_ok "$PYTHON" || die "after upgrading, $PYTHON can no longer 'import hallucinator'."
    after="$(hallucinator_version "$PYTHON")"
    if [ "$before" = "$after" ]; then
      printf 'HALLUCITE_OK: hallucinator %s (already current) at %s\n' "$after" "$PYTHON"
    else
      printf 'HALLUCITE_OK: hallucinator %s -> %s at %s\n' "$before" "$after" "$PYTHON"
    fi ;;
  audit)  exec "$PYTHON" "$SCRIPT_DIR/audit_references.py" "$@" ;;
  triage) exec "$PYTHON" "$SCRIPT_DIR/triage.py" "$@" ;;
  lint)   exec "$PYTHON" "$SCRIPT_DIR/lint_markdown.py" "$@" ;;
  python) exec "$PYTHON" "$@" ;;
esac
