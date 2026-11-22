#!/bin/sh
# 本地构建：先探测最快镜像源，再注入 build-arg 构建单镜像
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "[build] probing mirrors ..."
eval "$(sh "$ROOT/scripts/mirror_probe.sh" 2>/dev/null)"

echo "[build] docker build (apt=${APT_MIRROR} pip=${PIP_INDEX_URL} npm=${NPM_REGISTRY})"
docker build \
  --build-arg "APT_MIRROR=${APT_MIRROR}" \
  --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
  --build-arg "NPM_REGISTRY=${NPM_REGISTRY}" \
  -t flashtrip:local \
  -f "$ROOT/Dockerfile" \
  "$ROOT"

echo "[build] done: flashtrip:local"
