/** 无缝切换底图（核心）：setStyle 会销毁运行时 source/layer，故必须「快照 → 重放」。
 *  ① 相机快照 ② overlayRegistry 保存 source/layer spec、z-order、marker、选中态
 *  ③ switching=true 屏蔽交互 ④ setStyle ⑤ once('style.load') → jumpTo → 按 z 重放
 *  → 按新坐标系重建 marker → 恢复选中态 ⑥ 异常回滚 prevStyle，UI 全程显示「切换中」。
 */
import { ref, type Ref } from 'vue'
import type { Map as MlMap, StyleSpecification } from 'maplibre-gl'
import type { CoordSystem } from '@/lib/coord'
import type { MapStyleSpec } from '@/stores/map'
import {
  snapshotOverlays,
  restoreSourcesLayers,
  type OverlayMarker,
  type OverlaySnapshot,
} from './overlayRegistry'

export interface MapSwitchTarget {
  providerId: string
  style: string | MapStyleSpec
  coord: CoordSystem
}

export interface AppliedStyle {
  style: string | MapStyleSpec
  coord: CoordSystem
}

export interface MapSwitchHost {
  getMap: () => MlMap | null
  getMarkers: () => OverlayMarker[]
  getSelectedId: () => string | null
  /** DOM Marker 保守策略：全部 remove 后按新坐标系重建。 */
  rebuildMarkers: (markers: OverlayMarker[], coord: CoordSystem) => void
  restoreSelection: (id: string | null) => void
  /** 上一次成功应用的 style，用于异常回滚。 */
  getApplied: () => AppliedStyle | null
  onApplied?: (target: MapSwitchTarget) => void
}

export interface MapSwitchApi {
  switching: Ref<boolean>
  error: Ref<string>
  switchTo: (target: MapSwitchTarget) => Promise<boolean>
}

/** 用 style.load 事件把 setStyle 包装成 Promise；带超时，避免异常时永远卡在「切换中」。 */
function applyStyle(map: MlMap, style: string | MapStyleSpec): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true
        map.off('style.load', onLoad)
        reject(new Error('底图样式加载超时'))
      }
    }, 15000)
    const onLoad = () => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      resolve()
    }
    map.once('style.load', onLoad)
    try {
      map.setStyle(style as unknown as string | StyleSpecification)
    } catch (e) {
      if (!settled) {
        settled = true
        window.clearTimeout(timer)
        map.off('style.load', onLoad)
        reject(e as Error)
      }
    }
  })
}

export function useMapSwitch(host: MapSwitchHost): MapSwitchApi {
  const switching = ref(false)
  const error = ref('')

  /** 屏蔽地图交互：DOM Marker / 画布上的指针事件全部临时关闭。 */
  function setInteractive(map: MlMap, enabled: boolean): void {
    try {
      const canvas = map.getCanvasContainer()
      canvas.style.pointerEvents = enabled ? '' : 'none'
    } catch {
      /* 极少数未挂载容器场景忽略 */
    }
  }

  /** 把快照重放到某个 style 之上（切换成功与回滚共用）。 */
  async function replay(map: MlMap, snap: OverlaySnapshot, style: string | MapStyleSpec, coord: CoordSystem): Promise<void> {
    await applyStyle(map, style)
    map.jumpTo({
      center: snap.camera.center,
      zoom: snap.camera.zoom,
      bearing: snap.camera.bearing,
      pitch: snap.camera.pitch,
    })
    restoreSourcesLayers(map, snap, coord)
    host.rebuildMarkers(snap.markers, coord)
    host.restoreSelection(snap.selectedId)
  }

  async function switchTo(target: MapSwitchTarget): Promise<boolean> {
    const map = host.getMap()
    if (!map || switching.value) return false

    const snap = snapshotOverlays(map, host.getMarkers(), host.getSelectedId())
    const applied = host.getApplied()
    switching.value = true
    error.value = ''
    setInteractive(map, false)
    try {
      await replay(map, snap, target.style, target.coord)
      host.onApplied?.(target)
      return true
    } catch (e) {
      const reason = (e as Error)?.message || '未知错误'
      error.value = `底图切换失败：${reason}`
      // 回滚到切换前的 style 与坐标系，并恢复同一份叠加层快照
      if (applied) {
        try {
          await replay(map, snap, applied.style, applied.coord)
        } catch {
          error.value += '（回滚亦失败，请刷新页面）'
        }
      }
      return false
    } finally {
      setInteractive(map, true)
      switching.value = false
    }
  }

  return { switching, error, switchTo }
}
