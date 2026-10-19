#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
SRC="$ROOT/container-probe/runtime/companion"
OUT="$ROOT/artifacts/container/runtime"
PATH_IN_UPSTREAM=bionic/libm/upstream-freebsd/lib/msun/src
for tool in git cp; do command -v "$tool" >/dev/null; done
mkdir -p "$OUT/derived/$PATH_IN_UPSTREAM"
cp "$OUT/upstream/$PATH_IN_UPSTREAM/k_sincosl.h" \
    "$OUT/upstream/$PATH_IN_UPSTREAM/s_sincosl.c" "$OUT/derived/$PATH_IN_UPSTREAM/"
git apply --check --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
git apply --unsafe-paths --directory="$OUT/derived" "$SRC/platform.patch"
