#!/usr/bin/env bash
# Shared path contract for the copied flow scripts.
#
# Sourced, never executed.  The parallel workspace owns config/, data/ and
# output/; the installed career-ops checkout is only ever read.  Override any
# path with the matching CAREER_OPS_* environment variable, or put the values in
# config/career-ops.env (see config/career-ops.env.example).

_career_ops_default_home="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
_career_ops_base_home="${CAREER_OPS_HOME:-$_career_ops_default_home}"
_career_ops_env_dir="${CAREER_OPS_CONFIG:-$_career_ops_base_home/config}"
CAREER_OPS_ENV_FILE="${CAREER_OPS_ENV_FILE:-$_career_ops_env_dir/career-ops.env}"

if [ -f "$CAREER_OPS_ENV_FILE" ]; then
  # Fill only variables the real environment does not already define. Sourcing
  # the file directly would invert the documented precedence (real env wins).
  while IFS= read -r _career_ops_assignment; do
    case "$_career_ops_assignment" in
      [A-Za-z_]*=*) ;;
      *) continue ;;
    esac
    _career_ops_key="${_career_ops_assignment%%=*}"
    if [ -z "${!_career_ops_key+x}" ]; then
      export "$_career_ops_assignment"
    fi
  done < <(set -a; . "$CAREER_OPS_ENV_FILE" >/dev/null 2>&1; env)
  unset _career_ops_assignment _career_ops_key
fi

CAREER_OPS_HOME="${CAREER_OPS_HOME:-$_career_ops_base_home}"
CAREER_OPS_UPSTREAM="${CAREER_OPS_UPSTREAM:-$HOME/.local/share/career-ops}"
CAREER_OPS_CONFIG="${CAREER_OPS_CONFIG:-$CAREER_OPS_HOME/config}"
CAREER_OPS_DATA="${CAREER_OPS_DATA:-$CAREER_OPS_HOME/data}"
CAREER_OPS_OUTPUT="${CAREER_OPS_OUTPUT:-$CAREER_OPS_HOME/output}"
CAREER_OPS_SCRIPTS="${CAREER_OPS_SCRIPTS:-$CAREER_OPS_HOME/scripts}"

export CAREER_OPS_HOME CAREER_OPS_UPSTREAM CAREER_OPS_CONFIG
export CAREER_OPS_DATA CAREER_OPS_OUTPUT CAREER_OPS_SCRIPTS

# Prefer a workspace config file, then fall back to the read-only upstream one.
career_ops_read_config() {
  local name="$1"
  if [ -f "$CAREER_OPS_CONFIG/$name" ]; then
    printf '%s\n' "$CAREER_OPS_CONFIG/$name"
  else
    printf '%s\n' "$CAREER_OPS_UPSTREAM/config/$name"
  fi
}

career_ops_read_data() {
  local name="$1"
  if [ -f "$CAREER_OPS_DATA/$name" ]; then
    printf '%s\n' "$CAREER_OPS_DATA/$name"
  else
    printf '%s\n' "$CAREER_OPS_UPSTREAM/data/$name"
  fi
}

_career_ops_realpath() {
  if command -v realpath >/dev/null 2>&1; then
    realpath -m -- "$1"
  else
    python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"
  fi
}

# Refuse to write anything inside the read-only installed checkout.
career_ops_assert_not_upstream() {
  local candidate upstream
  candidate="$(_career_ops_realpath "$1")"
  upstream="$(_career_ops_realpath "$CAREER_OPS_UPSTREAM")"
  case "$candidate/" in
    "$upstream/"*)
      echo "ERRO: recusando ${2:-write} em $candidate: dentro do upstream read-only $upstream" >&2
      return 1
      ;;
  esac
}

# A misconfigured workspace must fail before any command can write upstream.
for _career_ops_dir in "$CAREER_OPS_CONFIG" "$CAREER_OPS_DATA" "$CAREER_OPS_OUTPUT"; do
  career_ops_assert_not_upstream "$_career_ops_dir" "diretório gravável" || exit 1
done
unset _career_ops_dir
