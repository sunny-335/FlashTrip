# 对象存储

瞬间的图片上传支持三种存储后端，配置位于「设置 → 存储」（config.json 的 `storage` 段），密钥加密存储（`*_enc`），读取时脱敏。

## local（默认）

保持零依赖：图片直接写入 `数据目录/uploads`，由后端直接提供访问。适合单机、流量小的部署。

## 阿里云 OSS

使用 `alibabacloud-oss-v2` SDK：

| 字段 | 说明 |
| --- | --- |
| `endpoint` | OSS Endpoint（如 `https://oss-cn-hangzhou.aliyuncs.com`） |
| `region` | 地域 |
| `bucket` | 桶名 |
| `access_key_id` / `access_key_secret` | 访问凭据（保存后加密为 `*_enc`） |
| `public_base_url` | 可选；配置后访问链接走公有桶直链 |
| `presign_ttl_seconds` | 预签名链接有效期，默认 7 天 |

## S3 兼容（MinIO / R2 等）

使用 boto3，`endpoint_url` 兼容任意 S3 协议服务：

| 字段 | 说明 |
| --- | --- |
| `endpoint_url` | 服务端点（MinIO、Cloudflare R2 等） |
| `region` | 地域 |
| `bucket` | 桶名 |
| `access_key_id` / `access_key_secret` | 访问凭据 |
| `public_base_url` | 可选；公有桶直链前缀 |
| `presign_ttl_seconds` | 预签名有效期，默认 7 天 |

## 访问链接策略

优先使用 `public_base_url`（适合配置了 CDN 或公有桶的场景）；未配置时生成预签名 URL（默认 7 天有效期）。

::: tip
密钥明文只在构造客户端的瞬间解密使用，读取配置一律脱敏为 `has_*` 布尔，不会出现在任何 API 响应或日志中。
:::
