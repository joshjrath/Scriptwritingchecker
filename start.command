#!/bin/bash
# Double-click this file in Finder, or run:  bash start.command
#
# Sets up everything the first time, and just starts the board after that.

set -e
cd "$(dirname "$0")"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }
oops() { printf "\n\033[31m%s\033[0m\n" "$1"; }

# --- Python -----------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  oops "Python is not installed."
  echo "macOS: open Terminal and run  xcode-select --install"
  echo "Then double-click this file again."
  exit 1
fi

VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
MAJOR=${VERSION%%.*}
MINOR=${VERSION##*.}
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]; }; then
  oops "Python $VERSION is too old; 3.9 or newer is needed."
  echo "Install a current version from https://www.python.org/downloads/"
  exit 1
fi

# --- dependencies -----------------------------------------------------------
if [ ! -d .venv ]; then
  say "Setting up (one minute, only happens once)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import discord, aiohttp" >/dev/null 2>&1; then
  say "Installing what it needs..."
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
fi

# --- first run or normal run ------------------------------------------------
if [ ! -f .env ] || [ ! -f scriptcheck.config.json ]; then
  python -m scriptcheck setup || exit $?
  echo
  read -r -p "Start the board now? [Y/n]: " REPLY
  case "$REPLY" in
    [Nn]*) echo "Later: double-click this file again."; exit 0 ;;
  esac
fi

ACCESS=$(grep '^SCRIPTCHECK_ACCESS_TOKEN=' .env | cut -d= -f2-)
say "Your board:  http://localhost:8080/?k=$ACCESS"
echo "Leave this window open. Press Control-C to stop."
echo

# Give the server a moment, then open the browser for them.
( sleep 3; command -v open >/dev/null && open "http://localhost:8080/?k=$ACCESS" ) &

python -m scriptcheck serve
