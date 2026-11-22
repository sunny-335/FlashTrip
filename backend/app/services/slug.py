"""行程目录名生成：中文转拼音全拼小写连写 + 4 位随机后缀。

pypinyin 是可选依赖（见 pyproject.toml）：已安装时用 lazy_pinyin 得到完整拼音；
未安装时回退到内置常用字表，保证后端在任何环境都能直接导入且不崩。
"""
from __future__ import annotations

import re
import secrets
import string

try:
    from pypinyin import lazy_pinyin as _lazy_pinyin
except Exception:  # 可选依赖缺失时降级，绝不影响应用启动
    _lazy_pinyin = None

_ALPHABET = string.ascii_lowercase + string.digits
_MAX_LEN = 40
_MAX_RETRY = 20

# 未安装 pypinyin 时的常用字兜底，覆盖常见旅游目的地与天数词
_FALLBACK = {
    "苏": "su", "州": "zhou", "三": "san", "日": "ri", "游": "you",
    "北": "bei", "京": "jing", "上": "shang", "海": "hai", "广": "guang",
    "深": "shen", "圳": "zhen", "杭": "hang", "西": "xi", "安": "an",
    "成": "cheng", "都": "du", "重": "chong", "庆": "qing", "南": "nan",
    "亚": "ya", "丽": "li", "江": "jiang", "大": "da", "理": "li",
    "桂": "gui", "林": "lin", "厦": "xia", "门": "men", "青": "qing",
    "岛": "dao", "昆": "kun", "明": "ming", "天": "tian", "之": "zhi",
    "行": "xing", "旅": "lv", "假": "jia", "期": "qi", "两": "liang",
    "四": "si", "五": "wu", "六": "liu", "七": "qi", "八": "ba",
    "九": "jiu", "十": "shi", "一": "yi", "二": "er", "周": "zhou",
    "末": "mo", "自": "zi", "然": "ran", "驾": "jia", "春": "chun",
    "夏": "xia", "秋": "qiu", "冬": "dong", "山": "shan", "水": "shui",
    "古": "gu", "城": "cheng", "湖": "hu",
}


def _to_pinyin(text: str) -> list[str]:
    """中文转全拼片段；非中文原样保留，交由 to_slug 统一处理。"""
    if _lazy_pinyin is not None:
        return [str(part).lower() for part in _lazy_pinyin(text)]
    out: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            py = _FALLBACK.get(ch)
            if py:
                out.append(py)
        else:
            out.append(ch)
    return out


def to_slug(title: str) -> str:
    """中文转拼音全拼小写连写；空格/标点转 '-'；截断 40；空则 trip。"""
    buf: list[str] = []
    for part in _to_pinyin(title or ""):
        for ch in str(part):
            if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
                buf.append(ch.lower())
            else:
                buf.append("-")
    slug = re.sub(r"-+", "-", "".join(buf)).strip("-")
    slug = slug[:_MAX_LEN].rstrip("-")
    return slug or "trip"


def _random_suffix(length: int = 4) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def trip_folder_name(title: str, *, existing: set[str] | None = None) -> str:
    """返回 <slug>-<4 位小写字母数字>；命中 existing 则重掷，最多 20 次。"""
    base = to_slug(title)
    taken = existing or set()
    for _ in range(_MAX_RETRY):
        name = f"{base}-{_random_suffix()}"
        if name not in taken:
            return name
    # 极端冲突时加长后缀，保证仍返回一个可用名字
    return f"{base}-{_random_suffix(8)}"
