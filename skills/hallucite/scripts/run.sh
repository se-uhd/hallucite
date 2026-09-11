#!/usr/bin/env bash
# run.sh -- the single entry point for the hallucite pipeline.
#
# Why this exists: when hallucite is installed as a Claude Code or Codex CLI plugin, only SKILL.md
# and these scripts ship. The dev-clone path (`mise run ...`) is not available, and the agent's
# shell often does not have `python3` on PATH even when it is installed under ~/.local/bin or
# Homebrew. Calling the .py scripts with a bare `python` then fails in confusing, easy-to-misread
# ways. This wrapper resolves an interpreter the pipeline can run on, then execs the requested
# script with it. There is nothing to install: the pipeline is standard library only.
#
# Contract for callers (see SKILL.md "Stop conditions" and the "Preflight" subsection):
#   - On success it is transparent: it runs the script and forwards its exit code.
#   - On any setup failure it prints a line beginning with `HALLUCITE_BOOTSTRAP_FAILED:` to stderr
#     and exits non-zero. That sentinel means NO audit ran -- there is no output to interpret.
#
# Usage:
#   run.sh check-env              # resolve an interpreter, then print HALLUCITE_OK / fail loud
#   run.sh audit  <pdf|dir> [...] # -> audit_references.py
#   run.sh triage <subcmd> [...]  # -> triage.py
#   run.sh lint   [...]           # -> lint_markdown.py
#   run.sh python [...]           # exec the resolved interpreter (escape hatch)
#
# Environment overrides:
#   HALLUCITE_PYTHON  the interpreter to use, verbatim
#   HALLUCITE_VENV    a venv an older install provisioned, reused if it is new enough
#                     (default: ${XDG_CACHE_HOME:-~/.cache}/hallucite/venv)

set -euo pipefail

FAIL="HALLUCITE_BOOTSTRAP_FAILED:"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." >/dev/null 2>&1 && pwd -P)"

# API keys for the online verification backends, if this tree has any. `.env.local` is gitignored
# and optional; mise reads the same file, so a dev clone and an installed plugin see the same
# values. A variable already set in the environment wins, so `S2_API_KEY=... run.sh audit ...`
# still overrides the file.
if [ -r "$REPO_ROOT/.env.local" ]; then
  while IFS='=' read -r key value; do
    key="${key%$'\r'}"; value="${value%$'\r'}"   # a file written on Windows
    key="${key#"${key%%[![:space:]]*}"}"          # leading space: an indented comment, or `export`
    key="${key%"${key##*[![:space:]]}"}"
    key="${key#export }"; key="${key#"${key%%[![:space:]]*}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%\"}"; value="${value#\"}"
    # Anything that is not a variable name is a comment, a blank line, or a line this reader does
    # not understand -- and none of those may take the audit down. `export` on a name with a space
    # in it fails, and under `set -e` that ended the run with no HALLUCITE_BOOTSTRAP_FAILED line,
    # which is the one thing this script promises never to do.
    case "$key" in ''|'#'*|*[!A-Za-z0-9_]*|[0-9]*) continue ;; esac
    [ -n "${!key:-}" ] || export "$key=$value"
  done < "$REPO_ROOT/.env.local"
fi
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

# The pipeline is standard library only, so "usable" means a new enough interpreter -- 3.10 for
# the `X | None` annotations these scripts are written in -- with sqlite3 built in, which is what
# the offline DBLP mirror is read through. There is nothing to install any more.
# Checks the *output*, not the exit status: plenty of executables accept `-c` and exit 0 without
# running anything (`/bin/echo` is the one that got past an exit-status probe), and a wrapper that
# accepts one of those hands the audit an interpreter that silently does nothing.
py_ok() {
  [ -n "${1:-}" ] && [ -x "$1" ] || return 1
  [ "$("$1" -c 'import sqlite3, sys
print("HALLUCITE_PY_OK" if sys.version_info >= (3, 10) else "old")' 2>/dev/null)" \
    = "HALLUCITE_PY_OK" ]
}

py_version() { "$1" -c 'import platform; print(platform.python_version())' 2>/dev/null || echo '?'; }

resolve_python() {
  # 1) explicit override -- used verbatim.
  if [ -n "${HALLUCITE_PYTHON:-}" ]; then
    py_ok "$HALLUCITE_PYTHON" || die \
      "\$HALLUCITE_PYTHON ($HALLUCITE_PYTHON) is not a usable interpreter: hallucite needs Python \
3.10 or newer with sqlite3. Point it at one, or unset it and let run.sh find one."
    printf '%s\n' "$HALLUCITE_PYTHON"; return 0
  fi
  # 2) a venv an older install provisioned still works if it is new enough.
  if py_ok "$VENV/bin/python"; then printf '%s\n' "$VENV/bin/python"; return 0; fi
  # 3) anything on PATH, or in the places a plugin's non-interactive shell tends to miss.
  local c base mise
  for c in python3 python3.13 python3.12 python3.11 python; do
    base="$(find_exe "$c" 2>/dev/null || true)"
    if py_ok "$base"; then printf '%s\n' "$base"; return 0; fi
  done
  # mise may have one installed that is not on PATH; use it, never auto-install through it.
  mise="$(find_exe mise 2>/dev/null || true)"
  if [ -n "$mise" ]; then
    for c in 3.13 3.12 3.11 3.10; do
      base="$("$mise" where "python@$c" 2>/dev/null || true)/bin/python$c"
      if py_ok "$base"; then printf '%s\n' "$base"; return 0; fi
    done
  fi
  die "no usable Python found. hallucite needs Python 3.10 or newer with sqlite3 and nothing else \
-- the pipeline is standard library only. Install one, or set \$HALLUCITE_PYTHON to an \
interpreter that qualifies."
}

cmd="${1:-}"
case "$cmd" in
  check-env|audit|triage|lint|python) shift ;;
  ""|-h|--help)
    printf 'usage: run.sh {check-env|audit|triage|lint|python} [args...]\n' >&2; exit 2 ;;
  *)
    printf '%s unknown command %q (expected check-env|audit|triage|lint|python)\n' \
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
    printf 'HALLUCITE_OK: %s (Python %s)\n' "$PYTHON" "$(py_version "$PYTHON")"
    # Non-fatal: the audit's extraction step needs pdftotext; warn now rather than failing later.
    find_exe pdftotext >/dev/null \
      || printf 'warning: pdftotext (poppler) not found; the audit needs it for PDF text extraction (e.g. brew install poppler).\n' >&2
    # Non-fatal: the offline mirror decides nine confirmations in ten, and an audit without one is
    # an incomplete audit rather than a broken one.
    dblp="${HALLUCITE_DBLP:-$HOME/hallucite/dblp.db}"
    [ -r "$dblp" ] \
      || printf 'warning: no offline DBLP mirror at %s; it decides most confirmations. Build it with `mise run build-dblp`.\n' "$dblp" >&2 ;;
  audit)  exec "$PYTHON" "$SCRIPT_DIR/audit_references.py" "$@" ;;
  triage) exec "$PYTHON" "$SCRIPT_DIR/triage.py" "$@" ;;
  lint)   exec "$PYTHON" "$SCRIPT_DIR/lint_markdown.py" "$@" ;;
  python) exec "$PYTHON" "$@" ;;
esac
