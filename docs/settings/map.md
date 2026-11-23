# 地图 Provider 配置

地图供应商在安装向导（第 4 步）或「设置 → 地图」中配置。密钥统一加密存储于 `/data/config.json` 的 `map` 段（`providers[].key_enc`），读取时脱敏为 `has_key` 布尔。

## 供应商速查

| 供应商 | 底图类型 | 瓦片密钥 | 服务密钥（POI / 路径规划） |
| --- | --- | --- | --- |
| OpenFreeMap | 矢量 | 不需要 | 不提供（无检索服务） |
| Mapbox | 矢量 | `tile_key`（token） | 同一 token |
| 高德地图 | 栅格 | 不需要（实测免密可用） | `service_key`（Web 服务 key） |
| 天地图 | 栅格 | `browser_tk` | `server_key` |

## 高德地图

- 栅格瓦片实测无 key 也可返回正常图片，因此**安装向导不会强制填写**。
- POI 检索、地理编码、路径规划走 Web 服务 key，需要在高德开放平台申请。
- 浏览器端安全配置（`js_key` / `security_js_code`）与服务端 key 分开存储，避免混用。

## 天地图

- 瓦片与注记图层都需要 `browser_tk`（浏览器端 token）；服务端接口（如检索）使用 `server_key`。
- 天地图注记图层作为内部子供应商自动挂载，复用母供应商的 tk，无需单独申请。

## Mapbox

- 使用 Access Token，瓦片 URL 模板中的 token 由后端代理注入，不会返回给前端。

## OpenFreeMap

- 完全免费、无需注册，内置多种样式（如 Liberty / Bright / Posron），开箱即用。
- 不提供 POI / 路径规划服务；需要检索功能时请切换或另行配置服务供应商。

## 安全要点

- 瓦片 URL 中的 `{key}` / `{token}` / `{access_token}` 占位符均由**后端代理注入**，密钥绝不拼进返回给前端的 style 对象。
- 未填任何密钥的供应商仍会出现在可选列表中（瓦片可用的场景），向导不做强制。
- 切换默认底图后，署名与审图号随预设元数据自动带出，满足合规展示要求。
