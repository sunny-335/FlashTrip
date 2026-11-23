# 本地开发

## 准备

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 22+ 与 pnpm（`corepack enable` 后自动获取）
- 本地构建文档站需要 pnpm（`cd docs && pnpm install`）

## 后端

```bash
cd backend
python -m pip install uv && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

本机开发时（无 `/data` 写权限）数据目录自动回退到项目内 `./data`，前端产物回退到 `frontend/dist`。

## 前端

```bash
cd frontend
pnpm install --allow-build=esbuild --allow-build=vue-demi
pnpm dev
```

前端产物由 `pnpm build` 生成到 `frontend/dist/`，生产环境由 FastAPI 统一托管。

## 文档站

```bash
cd docs
pnpm install
pnpm docs:dev      # 本地预览 http://localhost:5173/FlashTrip/
pnpm docs:build    # 产物输出到 docs/.vitepress/dist
```

::: tip 路由约定
文档站 `base` 为 `/FlashTrip/`，与后端 `static/docs` 挂载路径一致。生产镜像中由 Dockerfile 的 docs 构建阶段自动构建并复制，无需手动操作。
:::

## 测试

```bash
cd backend && uv run pytest -q          # 后端全量测试
cd frontend && pnpm test                # 前端单元测试
cd frontend && pnpm typecheck           # 类型检查
cd docs && pnpm docs:build              # 文档站构建验证
```

## 构建本地镜像

```bash
sh scripts/build.sh    # 自动探测镜像源并以 build-arg 注入
```
