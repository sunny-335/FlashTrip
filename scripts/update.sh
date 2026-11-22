#!/bin/sh
# 更新：拉取最新镜像，沿用现有容器的环境变量、端口、卷与重启策略重建容器。
# 数据保留在卷中；-e 参数（尤其 FLASHTRIP_SECRET_KEY）从旧容器继承，避免加密配置失效。
# 旧容器先改名保留，新容器启动失败时自动回滚。
# 可选覆盖：FLASHTRIP_IMAGE、FLASHTRIP_CONTAINER
set -eu

IMAGE=${FLASHTRIP_IMAGE:-ghcr.io/sunny-335/flashtrip:latest}
NAME=${FLASHTRIP_CONTAINER:-flashtrip}
PREV="${NAME}-prev"

echo "[update] 拉取 ${IMAGE}"
docker pull "$IMAGE"

if ! docker container inspect "$NAME" >/dev/null 2>&1; then
  if docker container inspect "$PREV" >/dev/null 2>&1; then
    echo "[update] 检测到上次中断的旧容器，先恢复"
    docker rename "$PREV" "$NAME"
  else
    echo "[update] 未找到容器 ${NAME}，请先按 README 的 docker run 命令创建" >&2
    exit 1
  fi
fi

# 逐项读取旧容器配置，拼成 docker run 参数（POSIX sh，无 jq / python 依赖）
set --
while IFS= read -r line; do
  if [ -n "$line" ]; then set -- "$@" -e "$line"; fi
done <<EOF
$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$NAME")
EOF

PORT_LINES=$(docker inspect --format '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{if .HostIP}}{{println (printf "%s:%s:%s" .HostIP .HostPort $p)}}{{else}}{{println (printf "%s:%s" .HostPort $p)}}{{end}}{{end}}{{end}}' "$NAME" 2>/dev/null || true)
if [ -z "$PORT_LINES" ]; then
  # 兼容个别 Docker 版本的字段差异：退化为不保留绑定 IP 的写法
  PORT_LINES=$(docker inspect --format '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{println (printf "%s:%s" .HostPort $p)}}{{end}}{{end}}' "$NAME" 2>/dev/null || true)
fi
while IFS= read -r line; do
  if [ -n "$line" ]; then set -- "$@" -p "$line"; fi
done <<EOF
$PORT_LINES
EOF

while IFS= read -r line; do
  if [ -n "$line" ]; then set -- "$@" -v "$line"; fi
done <<EOF
$(docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println (printf "%s:%s" .Name .Destination)}}{{else}}{{println (printf "%s:%s" .Source .Destination)}}{{end}}{{end}}' "$NAME")
EOF

RESTART=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$NAME")
if [ -n "$RESTART" ] && [ "$RESTART" != "no" ]; then
  set -- "$@" --restart "$RESTART"
fi

# 保留旧容器以便失败时回滚
docker rm -f "$PREV" >/dev/null 2>&1 || true
docker rename "$NAME" "$PREV"
echo "[update] 以新镜像重建 ${NAME}"
if docker run -d --name "$NAME" "$@" "$IMAGE"; then
  docker rm -f "$PREV" >/dev/null 2>&1 || true
  echo "[update] 完成；健康检查：docker exec ${NAME} sh -c 'curl -fsS http://127.0.0.1:${FLASHTRIP_PORT:-8000}/api/v1/health'"
else
  echo "[update] 启动失败，回滚到旧容器" >&2
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rename "$PREV" "$NAME"
  exit 1
fi
