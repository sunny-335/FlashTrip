#!/bin/sh
# 镜像源自动探测：TUNA → USTC → Aliyun → Tencent → official
# 输出可被 eval 的 KEY=VALUE；若设置 GITHUB_OUTPUT，则同时输出小写键供 workflow 使用。
# 探测失败一律回退 official，绝不阻断构建。
set -u

APT_CANDIDATES="mirrors.tuna.tsinghua.edu.cn mirrors.ustc.edu.cn mirrors.aliyun.com mirrors.cloud.tencent.com deb.debian.org"
PIP_CANDIDATES="https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.ustc.edu.cn/pypi/simple https://mirrors.aliyun.com/pypi/simple https://mirrors.cloud.tencent.com/pypi/simple https://pypi.org/simple"
NPM_CANDIDATES="https://registry.npmmirror.com https://mirrors.cloud.tencent.com/npm/ https://registry.npmjs.org"

probe() {
  # $1 = label, $2 = space-separated urls, $3 = probe path suffix
  label="$1"
  urls="$2"
  suffix="${3:-}"
  best=""
  best_time=999
  for u in $urls; do
    target="${u}${suffix}"
    t=$(curl -sS -o /dev/null -w '%{time_total}' -m 3 --connect-timeout 2 "$target" 2>/dev/null || echo "")
    if [ -n "$t" ]; then
      # 取整数比较（POSIX sh 无浮点比较，用 awk）
      faster=$(awk -v a="$t" -v b="$best_time" 'BEGIN{print (a<b)?"1":"0"}')
      if [ "$faster" = "1" ]; then best_time="$t"; best="$u"; fi
    fi
  done
  if [ -z "$best" ]; then
    # 回退到最后一项（official），由调用方按列表末位取值
    best=$(printf '%s' "$urls" | awk '{print $NF}')
  fi
  echo "[mirror_probe] ${label} -> ${best} (${best_time}s)" >&2
  printf '%s' "$best"
}

APT_MIRROR=$(probe apt "$APT_CANDIDATES" "/debian/dists/stable/Release")
PIP_INDEX_URL=$(probe pip "$PIP_CANDIDATES" "")
NPM_REGISTRY=$(probe npm "$NPM_CANDIDATES" "")

printf 'APT_MIRROR=%s\nPIP_INDEX_URL=%s\nNPM_REGISTRY=%s\n' "$APT_MIRROR" "$PIP_INDEX_URL" "$NPM_REGISTRY"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'apt_mirror=%s\npip_index_url=%s\nnpm_registry=%s\n' \
    "$APT_MIRROR" "$PIP_INDEX_URL" "$NPM_REGISTRY" >> "$GITHUB_OUTPUT"
fi
