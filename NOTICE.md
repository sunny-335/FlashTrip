# NOTICE — 瞬旅 FlashTrip

## 关于参考项目 TREK

本项目在信息架构与交互层面参考了开源项目 [TREK](https://github.com/liketrek/TREK)
（导航结构、行程三栏布局、拖拽排序、PDF/ICS 导出等产品设计思路）。

- TREK 采用 **AGPL-3.0** 许可证。
- FlashTrip 采用 **MIT** 许可证，**未复制、未移植、未改编 TREK 的任何源代码、静态资源或文案**。
- 全部代码为自研实现，技术栈为 Vue 3 + FastAPI。
- 贡献时请勿从 AGPL-3.0 项目粘贴代码。

## 第三方依赖

前端 Vue 3 / Vite / Reka UI / Tailwind CSS / MapLibre GL JS / vue-draggable-plus，
后端 FastAPI / SQLAlchemy / Pydantic 等均为宽松许可。清单可在构建时生成：

- `pnpm licenses list --json > THIRD_PARTY_FRONTEND.json`
- `uv run pip-licenses --format=json > THIRD_PARTY_BACKEND.json`

使用 OpenFreeMap 与 OpenStreetMap 数据时必须保留 attribution。
