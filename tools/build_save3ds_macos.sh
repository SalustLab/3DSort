#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${SAVE3DS_SOURCE_DIR:-$ROOT_DIR/.cache/save3ds}"
OUTPUT="$ROOT_DIR/tools/save3ds/save3ds_fuse"

if [[ ! -f "$SOURCE_DIR/save3ds_fuse/Cargo.toml" ]]; then
  mkdir -p "$(dirname "$SOURCE_DIR")"
  git clone https://github.com/wwylele/save3ds "$SOURCE_DIR"
fi

cargo build \
  --manifest-path "$SOURCE_DIR/save3ds_fuse/Cargo.toml" \
  --release \
  --no-default-features

install -m 755 "$SOURCE_DIR/target/release/save3ds_fuse" "$OUTPUT"
printf 'Built %s\n' "$OUTPUT"
