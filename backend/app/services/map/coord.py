"""坐标系转换：WGS84 <-> GCJ-02 <-> BD-09（与前端 gcoord 同源算法）。

业务坐标统一 WGS84 入库 + coord_system 标记：
  - POI 入库前：to_wgs84(lng, lat, 数据源坐标系)（出国减偏）
  - 渲染时：from_wgs84(lng, lat, 底图坐标系)（回国加偏）
CGCS2000 与 WGS84 在厘米级内一致，按「不转换」处理，仅保留标记。
"""
from __future__ import annotations

import math

PI = 3.1415926535897932384626
_A = 6378245.0                       # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323         # 偏心率平方
_X_PI = PI * 3000.0 / 180.0

COORD_SYSTEMS = ("WGS84", "GCJ02", "BD09", "CGCS2000")

_ALIASES = {
    "wgs84": "WGS84", "wgs-84": "WGS84", "epsg:4326": "WGS84", "epsg4326": "WGS84",
    "gcj02": "GCJ02", "gcj-02": "GCJ02", "gcj2": "GCJ02", "amap": "GCJ02",
    "bd09": "BD09", "bd-09": "BD09", "bd9": "BD09", "baidu": "BD09",
    "cgcs2000": "CGCS2000", "cgcs-2000": "CGCS2000", "epsg:4490": "CGCS2000",
    "tianditu": "CGCS2000",
}


def _norm(system: str) -> str:
    """规范化坐标系名称；未知值直接报错，绝不静默按 WGS84 处理（会造成数百米偏移）。"""
    key = str(system or "").strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    if key.upper() in COORD_SYSTEMS:
        return key.upper()
    raise ValueError(f"未知坐标系：{system!r}，可选 {COORD_SYSTEMS}")


def _out_of_china(lng: float, lat: float) -> bool:
    """境外（含港澳台部分边缘）不做加偏/减偏。"""
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def _delta(lng: float, lat: float) -> tuple[float, float]:
    """给定坐标处的 GCJ-02 偏移量（度）。"""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = 1.0 - _EE * math.sin(radlat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrt_magic) * PI)
    dlng = (dlng * 180.0) / (_A / sqrt_magic * math.cos(radlat) * PI)
    return dlng, dlat


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS84 -> GCJ-02（出国加偏）。"""
    if _out_of_china(lng, lat):
        return lng, lat
    dlng, dlat = _delta(lng, lat)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 -> WGS84（回国减偏）。

    先用 gcoord 标准减偏公式得到初值，再做数次不动点迭代精化，
    保证 WGS84 -> GCJ-02 -> WGS84 往返误差达到亚米级（纯标准公式约 1~2m）。
    """
    if _out_of_china(lng, lat):
        return lng, lat
    dlng, dlat = _delta(lng, lat)
    w_lng, w_lat = lng - dlng, lat - dlat
    for _ in range(6):
        g_lng, g_lat = wgs84_to_gcj02(w_lng, w_lat)
        d_lng, d_lat = lng - g_lng, lat - g_lat
        if abs(d_lng) < 1e-11 and abs(d_lat) < 1e-11:
            break
        w_lng += d_lng
        w_lat += d_lat
    return w_lng, w_lat


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 -> BD-09（百度二次加密）。"""
    z = math.hypot(lng, lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """BD-09 -> GCJ-02（百度反解）。

    闭合公式中的 `sin(y * X_PI)` / `cos(x * X_PI)` 用减常量后的坐标计算，
    与正向公式用 GCJ-02 原坐标计算存在系统性残差（约 4e-7 度 ≈ 4cm）。
    这里用正向公式做少量不动点修正，把残差压到 1e-9 度以内。
    """
    x, y = lng - 0.0065, lat - 0.006
    gx, gy = x, y
    for _ in range(4):
        z = math.hypot(x, y) - 0.00002 * math.sin(y * _X_PI)
        theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
        gx, gy = z * math.cos(theta), z * math.sin(theta)
        bx, by = gcj02_to_bd09(gx, gy)
        dx, dy = lng - bx, lat - by
        if abs(dx) < 1e-13 and abs(dy) < 1e-13:
            break
        x += dx
        y += dy
    return gx, gy


def _to_wgs84(lng: float, lat: float, system: str) -> tuple[float, float]:
    if system in ("WGS84", "CGCS2000"):
        return lng, lat
    if system == "GCJ02":
        return gcj02_to_wgs84(lng, lat)
    if system == "BD09":
        return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))
    raise ValueError(f"未支持的坐标系：{system}")


def _from_wgs84(lng: float, lat: float, system: str) -> tuple[float, float]:
    if system in ("WGS84", "CGCS2000"):
        return lng, lat
    if system == "GCJ02":
        return wgs84_to_gcj02(lng, lat)
    if system == "BD09":
        return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))
    raise ValueError(f"未支持的坐标系：{system}")


def transform(lng: float, lat: float, frm: str, to: str) -> tuple[float, float]:
    """任意坐标系互转：统一先回到 WGS84 再转到目标坐标系。

    境外（含港澳台边缘）一律直通 —— 与前端 gcoord 行为一致：
    国内加偏算法本就不适用于境外，BD-09 的常量偏移也不应作用于境外坐标。
    """
    src, dst = _norm(frm), _norm(to)
    if _out_of_china(lng, lat):
        return lng, lat
    if src == dst or (src in ("WGS84", "CGCS2000") and dst in ("WGS84", "CGCS2000")):
        return lng, lat
    return _from_wgs84(*_to_wgs84(lng, lat, src), dst)


def to_wgs84(lng: float, lat: float, frm: str) -> tuple[float, float]:
    """把任意来源坐标归一化为 WGS84（入库前调用）。"""
    system = _norm(frm)
    if _out_of_china(lng, lat):
        return lng, lat
    return _to_wgs84(lng, lat, system)


def from_wgs84(lng: float, lat: float, to: str) -> tuple[float, float]:
    """把 WGS84 坐标转换到目标底图坐标系（渲染前调用）。"""
    system = _norm(to)
    if _out_of_china(lng, lat):
        return lng, lat
    return _from_wgs84(lng, lat, system)
