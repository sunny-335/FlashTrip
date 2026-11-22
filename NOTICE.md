# NOTICE — 瞬旅 FlashTrip

## 关于参考项目 TREK

本项目在**信息架构与交互层面**参考了开源项目 [TREK](https://github.com/liketrek/TREK)
（导航结构、行程三栏布局、拖拽排序、PDF/ICS 导出等产品设计思路）。

- TREK 采用 **AGPL-3.0** 许可证。
- FlashTrip 采用 **MIT** 许可证，**未复制、未移植、未改编 TREK 的任何源代码、静态资源或文案**。
- 全部代码为自研实现，技术栈亦不同（Vue3 + FastAPI，而非 React + NestJS）。
- 贡献时请勿从 AGPL-3.0 项目粘贴代码；CI 中的依赖许可证扫描会拦截 AGPL 依赖。

## 第三方依赖许可（构建时自动生成清单）

- 前端：`pnpm licenses list --json > THIRD_PARTY_FRONTEND.json`
- 后端：`uv run pip-licenses --format=json > THIRD_PARTY_BACKEND.json`

主要依赖许可：Vue 3 / Vite / shadcn-vue / Reka UI / Tailwind CSS / MapLibre GL JS /
vue-draggable-plus / OpenFreeMap (MIT) / FastAPI / SQLAlchemy / Pydantic 均为宽松许可。
OpenFreeMap 与 OpenStreetMap 数据使用时**必须保留 attribution**。

## 地图合规提示

在中国大陆面向公众提供地图服务，需使用经审核批准的地图并标注**审图号**、完成 ICP 备案。
OpenFreeMap / OSM / Mapbox 等境外数据源无中国审图号，仅建议用于境外行程或个人自用；
本产品在设置页提供审图号配置位与风险提示，**不声称已取得合规资质**。
具体法律义务请自行咨询法务。
