/* 瞬旅离线 Service Worker（手写，零依赖）。
 * 策略：静态资源（/assets/、图标、manifest）cache-first；
 *       导航请求 network-first，失败回退缓存的 index.html；
 *       所有 /api/ 请求一律不缓存、不拦截（避免登录态与业务数据陈旧）。
 * 修改 VERSION 即可让 activate 清理旧缓存并全量升级。 */
const VERSION = 'flashtrip-v1'
const CACHE_NAME = `flashtrip-static-${VERSION}`
const APP_SHELL = ['/', '/index.html']
const API_PREFIX = '/api/'
const ASSET_PREFIX = '/assets/'
const STATIC_EXT = /\.(?:js|css|png|jpg|jpeg|gif|svg|webp|ico|woff2?|ttf|otf|map|webmanifest)$/i

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME)
      await cache.addAll(APP_SHELL)
      await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(
        keys
          .filter((key) => key.startsWith('flashtrip-') && key !== CACHE_NAME)
          .map((key) => caches.delete(key)),
      )
      await self.clients.claim()
    })(),
  )
})

/** 判断是否按静态资源处理：构建产物、图标与清单文件。 */
function isStaticAsset(pathname) {
  return pathname.startsWith(ASSET_PREFIX) || pathname === '/manifest.webmanifest' || STATIC_EXT.test(pathname)
}

/** 静态资源优先读缓存，未命中再联网并回写缓存。 */
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response && response.ok && response.type === 'basic') {
    await cache.put(request, response.clone())
  }
  return response
}

/** 导航优先联网，离线或网络异常时回退到缓存的应用壳。 */
async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME)
  try {
    const response = await fetch(request)
    if (response && response.ok) {
      await cache.put('/index.html', response.clone())
    }
    return response
  } catch {
    return (await cache.match('/index.html')) || (await cache.match('/')) || Response.error()
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  let url
  try {
    url = new URL(request.url)
  } catch {
    return
  }
  if (url.origin !== self.location.origin) return
  // 接口请求完全绕过 Service Worker，不缓存、不改写
  if (url.pathname.startsWith(API_PREFIX)) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request))
    return
  }
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request))
  }
  // 其余同源请求直接走网络，不做任何缓存
})
