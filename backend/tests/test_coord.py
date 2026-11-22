"""坐标转换：GCJ-02 / BD-09 已知点往返精度、境外不偏移、CGCS2000 等价 WGS84。"""
from __future__ import annotations

import math

import pytest

from app.services.map.coord import (
    COORD_SYSTEMS,
    bd09_to_gcj02,
    from_wgs84,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    to_wgs84,
    transform,
    wgs84_to_gcj02,
)

# 中国境内已知 WGS84 参考点：北京天安门 / 上海人民广场 / 广州
POINTS = ((116.397428, 39.90923), (121.473701, 31.230416), (113.264385, 23.129112))


def _distance_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Haversine 球面距离（米）。"""
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def test_gcj02_offset_is_significant():
    """出国加偏后应产生 50~1000m 量级偏移，且坐标确实改变。"""
    for lng, lat in POINTS:
        g_lng, g_lat = wgs84_to_gcj02(lng, lat)
        assert g_lng != lng and g_lat != lat
        assert 50 < _distance_m(lng, lat, g_lng, g_lat) < 1000


def test_gcj02_roundtrip_under_1m():
    """核心精度要求：WGS84 -> GCJ-02 -> WGS84 误差 < 1m。"""
    for lng, lat in POINTS:
        g_lng, g_lat = wgs84_to_gcj02(lng, lat)
        w_lng, w_lat = gcj02_to_wgs84(g_lng, g_lat)
        assert _distance_m(lng, lat, w_lng, w_lat) < 1.0


def test_bd09_roundtrip_under_1m():
    """BD-09 二次加密链回到 WGS84 同样 < 1m。"""
    for lng, lat in POINTS:
        b_lng, b_lat = gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))
        w_lng, w_lat = to_wgs84(b_lng, b_lat, "BD09")
        assert _distance_m(lng, lat, w_lng, w_lat) < 1.0
        # BD-09 -> GCJ-02 精确反解
        g_lng, g_lat = wgs84_to_gcj02(lng, lat)
        r_lng, r_lat = bd09_to_gcj02(b_lng, b_lat)
        assert abs(r_lng - g_lng) < 1e-7 and abs(r_lat - g_lat) < 1e-7


def test_generic_transform_matches_direct_chain():
    lng, lat = POINTS[0]
    b_lng, b_lat = from_wgs84(lng, lat, "BD09")
    assert transform(lng, lat, "WGS84", "BD09") == (b_lng, b_lat)
    assert transform(b_lng, b_lat, "BD-09", "GCJ-02") == pytest.approx(
        wgs84_to_gcj02(lng, lat), abs=1e-5
    )
    assert transform(lng, lat, "GCJ02", "GCJ02") == (lng, lat)


def test_cgcs2000_equals_wgs84():
    lng, lat = POINTS[1]
    assert to_wgs84(lng, lat, "CGCS2000") == (lng, lat)
    assert from_wgs84(lng, lat, "CGCS2000") == (lng, lat)
    assert transform(lng, lat, "CGCS2000", "WGS84") == (lng, lat)


def test_out_of_china_no_offset():
    lng, lat = -0.1276, 51.5072  # 伦敦
    assert wgs84_to_gcj02(lng, lat) == (lng, lat)
    assert gcj02_to_wgs84(lng, lat) == (lng, lat)
    assert to_wgs84(lng, lat, "BD09") == (lng, lat)
    assert from_wgs84(lng, lat, "GCJ02") == (lng, lat)


def test_aliases_and_unknown_system():
    lng, lat = POINTS[2]
    assert to_wgs84(*wgs84_to_gcj02(lng, lat), "gcj-02") == pytest.approx((lng, lat), abs=1e-5)
    assert "WGS84" in COORD_SYSTEMS and "CGCS2000" in COORD_SYSTEMS
    with pytest.raises(ValueError):
        transform(lng, lat, "MARS", "WGS84")
