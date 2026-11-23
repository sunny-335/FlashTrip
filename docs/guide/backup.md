# 备份

## 备份内容

备份覆盖数据库、`/data/config.json` 与上传文件，打包为单一归档文件，保存在 `/data` 卷内。

## 定时备份

- 应用内置备份调度线程，随启动自动运行，异常不会阻断服务。
- 备份间隔与保留数量可在设置页调整。

## 手动导入导出

- **导出**：在设置页下载完整备份归档。
- **导入**：上传归档后自动校验并恢复数据库与配置；导入前建议先手动导出一次当前状态。

::: warning 主密钥
备份归档中的加密密钥依赖 `FLASHTRIP_SECRET_KEY`（或 config.json 中的 `secret_key`）。恢复到新环境时必须使用**同一主密钥**，否则已加密的 LLM / 地图 / 邮件 / 天气密钥无法解密。
:::

## 数据卷

所有持久数据（SQLite 数据库、配置、上传、日志、备份）都在 `/data` 卷中：

```bash
docker volume inspect flashtrip-data   # 查看卷位置
docker run --rm -v flashtrip-data:/data -v $PWD:/out alpine cp -r /data /out/backup
```

删除容器不会删除卷；`docker volume rm` 前请确认已备份。
