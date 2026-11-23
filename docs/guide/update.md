# 版本更新

镜像发布后，任选一种方式更新。数据保存在 `flashtrip-data` 卷中，不会随容器删除丢失。

::: danger 关键前提
**必须沿用首次部署的 `FLASHTRIP_SECRET_KEY`**，否则已加密的 API Key 无法解密。
:::

## 一键脚本

自动继承旧容器的环境变量、端口、卷与重启策略，启动失败自动回滚：

```bash
sh scripts/update.sh
```

## 单行命令

不依赖仓库，参数按实际部署调整：

```bash
docker pull ghcr.io/sunny-335/flashtrip:latest \
  && docker rm -f flashtrip \
  && docker run -d --name flashtrip -p 8000:8000 \
     -v flashtrip-data:/data -e TZ=Asia/Shanghai \
     -e FLASHTRIP_SECRET_KEY="<与首次部署一致>" \
     --restart unless-stopped ghcr.io/sunny-335/flashtrip:latest
```

## Docker Compose

```bash
docker compose pull && docker compose up -d --force-recreate
```

## 更新后确认

```bash
docker exec flashtrip curl -fsS http://127.0.0.1:8000/api/v1/health
```

容器启动时会自动执行数据库迁移（`alembic upgrade head`），无需手动操作。

## 镜像标签

- `latest`：main 分支最新构建
- `main`：main 分支
- `v*`：版本标签
- `<sha>`：提交短哈希
