#!/usr/bin/env bash
set -euo pipefail

# Builds the native save3ds helper for macOS (and Linux) from source, pinned
# to the tag below so the build is reproducible. FUSE is disabled: 3DSort only
# uses extract/import. The output lands in tools/save3ds/ and is gitignored on
# purpose; compiled binaries never enter the repo.
SAVE3DS_TAG="${SAVE3DS_TAG:-v1.4.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${SAVE3DS_SOURCE_DIR:-$ROOT_DIR/.cache/save3ds}"
OUTPUT="$ROOT_DIR/tools/save3ds/save3ds_fuse"

if [[ ! -f "$SOURCE_DIR/save3ds_fuse/Cargo.toml" ]]; then
  rm -rf "$SOURCE_DIR"  # an interrupted clone leaves a half dir git refuses to reuse
  mkdir -p "$(dirname "$SOURCE_DIR")"
  git clone --depth 1 --branch "$SAVE3DS_TAG" \
    https://github.com/wwylele/save3ds "$SOURCE_DIR"
fi

cargo build \
  --manifest-path "$SOURCE_DIR/save3ds_fuse/Cargo.toml" \
  --release \
  --no-default-features

install -m 755 "$SOURCE_DIR/target/release/save3ds_fuse" "$OUTPUT"
printf 'Built %s\n' "$OUTPUT"
