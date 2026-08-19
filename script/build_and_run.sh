#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
APP_BUNDLE="$ROOT_DIR/dist/3DSort.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/3DSort"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON; create the project virtual environment first." >&2
  exit 1
fi

stop_existing() {
  pkill -f "$APP_BINARY" >/dev/null 2>&1 || true
}

build() {
  cd "$ROOT_DIR"
  if [[ ! -x "$ROOT_DIR/tools/save3ds/save3ds_fuse" ]]; then
    "$ROOT_DIR/tools/build_save3ds_macos.sh"
  fi
  "$PYTHON" -m PyInstaller --clean --noconfirm "$ROOT_DIR/3DSort.macos.spec"
}

open_mock() {
  /usr/bin/open -n "$APP_BUNDLE" --args --mock
}

stop_existing
build

case "$MODE" in
  run)
    open_mock
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY" --mock
    ;;
  --logs|logs)
    open_mock
    /usr/bin/log stream --info --style compact --predicate 'process == "3DSort"'
    ;;
  --telemetry|telemetry)
    open_mock
    /usr/bin/log stream --info --style compact --predicate 'process == "3DSort"'
    ;;
  --verify|verify)
    open_mock
    sleep 2
    pgrep -f "$APP_BINARY" >/dev/null
    stop_existing
    echo "3DSort.app launched successfully"
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
