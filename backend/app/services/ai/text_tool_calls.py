"""文本形式工具调用拦截：跨 chunk 的有状态缓冲解析器（状态机）。

背景：部分模型（尤其国产 OpenAI 兼容端点）在降级或未正确走结构化 tool_calls
通道时，会把工具调用以**文本形式**混进正文输出，例如：

    {"name": "get_weather", "arguments": {"city": "北京"}}
    ```json
    {"name": "get_weather", "arguments": {"city": "北京"}}
    ```
    [tool_call]{"name": "get_weather","arguments":{...}}[/tool_call]
    to=functions.get_weather {"city": "北京"}

这类协议原文直接流式转发给用户就是「看到原始调用文本」的根因。本模块在
delta 转发前做拦截：候选文本先缓冲、再判定；判定为工具调用则抑制输出并
产出结构化调用，判定不是则把已缓冲内容原样作为 delta 补发。

设计原则（保守优先）：宁可漏判（当正文输出）不可误判（吃掉正文）。
因此只有满足「行首起始 + 形状完整（工具名 + 参数对象）」才会被拦截；
普通 Markdown、行内 JSON、示例代码块都会原样放行。
"""
from __future__ import annotations

import json
import re
from typing import Any

# 动作类型：delta=正文增量（原样转发）；tool_call=拦截成功产出的结构化调用
ACTION_DELTA = "delta"
ACTION_TOOL_CALL = "tool_call"

# 行首可识别的候选起始标记；出现即先缓冲判定，判定不成立原样补发。
# 注意：长标记必须排在短标记前面（如 ```json 在 ``` 之前）。
_LINE_MARKERS: tuple[str, ...] = (
    "```json", "```jsonc", "```JSON", "```tool", "```",  # 代码围栏形态
    "〔tool_call〕", "[tool_call]", "<tool_call", "<function_call",  # 特殊标记形态
    "assistant to=functions.", "to=functions.",  # 原始伪协议形态
    "tool_call:", "tool_call：",
    "{",  # 行首裸 JSON 对象（独立段落形态）
)

_CANDIDATE_RE = re.compile(
    r"^[ \t]*(?:" + "|".join(re.escape(m) for m in _LINE_MARKERS) + ")",
    re.MULTILINE,
)
_FENCE_OPEN_RE = re.compile(r"^[ \t]*```[^\n{]*")
_FENCE_CLOSE_RE = re.compile(r"\n```[ \t]*(?:\r?\n|$)")
_TO_FUNCTIONS_NAME_RE = re.compile(r"to=functions\.([A-Za-z0-9_.\-]+)")

# 标记形态对应的闭标签（判定成功后一并吞掉，避免协议残骸漏给用户）
_TAG_CLOSE: tuple[tuple[str, str], ...] = (
    ("〔tool_call〕", "〔/tool_call〕"),
    ("[tool_call]", "[/tool_call]"),
    ("<tool_call", "</tool_call"),
    ("<function_call", "</function_call"),
)

# 工具调用形状约束：工具名必须是简单标识符（可带 functions. 前缀），长度有限
_CALL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,63}$")
_NAME_KEYS = ("name", "tool", "tool_name")
_ARG_KEYS = ("arguments", "parameters", "args", "input")
# 标记后允许向前找参数 JSON 的最大窗口，超出视为普通正文
_LABEL_WINDOW = 200

_MISSING = object()


def _bracket_end(text: str, start: int, opener: str, closer: str) -> int | None:
    """从 text[start]（必须为 opener）起找配对的 closer 下标；未闭合返回 None。

    字符串感知：跳过双引号内（含转义）的内容，避免 JSON 字符串里的括号干扰配对。
    """
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
    return None


def _load_json_candidate(text: str) -> Any:
    """从文本中提取首个完整 JSON 值（对象或数组）；提取不到返回 _MISSING。"""
    stripped = text.strip()
    if not stripped:
        return _MISSING
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    # 文本里混有其它内容（标记、说明等）：截取首个配对完整的括号段再试
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start == -1:
            continue
        end = _bracket_end(stripped, start, opener, closer)
        if end is None:
            continue
        try:
            return json.loads(stripped[start:end + 1])
        except ValueError:
            continue
    return _MISSING


def _normalize_call(obj: Any) -> dict | None:
    """把一个 JSON 对象归一化为 {id, name, arguments} 工具调用；形状不符返回 None。"""
    if not isinstance(obj, dict):
        return None
    spec = dict(obj)
    # OpenAI 结构化形态：{"function": {"name": ..., "arguments": "..."}}
    fn = spec.get("function")
    if isinstance(fn, dict):
        merged = dict(fn)
        if spec.get("id") and not merged.get("id"):
            merged["id"] = spec["id"]
        spec = merged
    name = ""
    for key in _NAME_KEYS:
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            break
    if not name:
        return None
    for prefix in ("functions.", "plugins."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if not _CALL_NAME_RE.match(name):
        return None
    arguments = None
    for key in _ARG_KEYS:
        if key in spec:
            arguments = spec[key]
            break
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    return {
        "id": str(spec.get("id") or ""),
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }


def _calls_from_data(data: Any) -> list[dict]:
    """把已加载的 JSON 值映射为工具调用列表；不是调用形状返回空列表。"""
    if isinstance(data, list):
        calls = [_normalize_call(item) for item in data]
        # 数组形态必须整体都是调用，混有其它内容则按正文放行（保守）
        return [c for c in calls if c] if calls and all(calls) else []
    if isinstance(data, dict):
        # {"tool_calls": [{...}, ...]} 批量形态
        batch = data.get("tool_calls")
        if isinstance(batch, list):
            calls = [_normalize_call(item) for item in batch]
            if calls and len(calls) == len(batch):
                return [c for c in calls if c]
            return []
        call = _normalize_call(data)
        return [call] if call else []
    return []


def _parse_calls(text: str) -> list[dict]:
    """把候选文本解析为工具调用列表；解析不出合法调用返回空列表。"""
    data = _load_json_candidate(text)
    if data is _MISSING:
        return []
    return _calls_from_data(data)


def _kind_of(text: str) -> str:
    """根据候选缓冲行首内容判定候选类型。"""
    stripped = text.lstrip(" \t")
    if stripped.startswith("```"):
        return "fence"
    if stripped.startswith("{"):
        return "json"
    for open_marker, _close in _TAG_CLOSE:
        if stripped.startswith(open_marker):
            return "tag"
    if stripped.startswith("to=functions."):
        return "to_functions"
    if stripped.startswith("tool_call:") or stripped.startswith("tool_call："):
        return "label"
    return "unknown"


class TextToolCallParser:
    """有状态跨块缓冲解析器。

    状态机：
      scan（正文直通）——在缓冲里找行首候选标记；找不到则放行，
          仅保留末尾可能构成「标记前缀」的一小段等下一个 chunk；
          找到则把标记前的文本作为 delta 放行，进入 hold。
      hold（候选缓冲）——持续累积直到能判定：
          判定为工具调用 → 产出 ACTION_TOOL_CALL（不发 delta）；
          判定不是 → 把整段缓冲作为一条 delta 原样补发；
          数据不足 → 继续等（超过 max_hold 或流结束则按正文放行）。
      两种状态在 _drain 循环内交替，直到缓冲耗尽。
    """

    def __init__(self, *, max_hold: int = 4096) -> None:
        self._buf = ""
        self._holding = False
        self._max_hold = max_hold

    # ------------------------------------------------------------------ 对外接口
    def feed(self, piece: str) -> list[tuple[str, Any]]:
        """流入一个文本块，返回可立即放行的动作列表。"""
        if piece:
            self._buf += piece
        return self._drain(final=False)

    def flush(self) -> list[tuple[str, Any]]:
        """流结束时冲刷：未判定完的候选一律按正文放行（宁可漏判）。"""
        out = self._drain(final=True)
        if self._buf:
            out.append((ACTION_DELTA, self._buf))
            self._buf = ""
            self._holding = False
        return out

    # ------------------------------------------------------------------ 内部实现
    def _hold_tail(self, buf: str) -> int:
        """保留末尾可能是「标记前缀」的片段长度，等下一个 chunk 再判定。"""
        tail = buf.rsplit("\n", 1)[-1]
        if not tail:
            return 0
        for marker in _LINE_MARKERS:
            if marker.startswith(tail):
                return len(tail)
        return 0

    def _drain(self, *, final: bool) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        while self._buf:
            if not self._holding:
                match = _CANDIDATE_RE.search(self._buf)
                if match is None:
                    hold = 0 if final else self._hold_tail(self._buf)
                    cut = len(self._buf) - hold
                    if cut:
                        out.append((ACTION_DELTA, self._buf[:cut]))
                    self._buf = self._buf[cut:]
                    return out  # 尾部需要更多数据，等待下一次 feed
                if match.start():
                    out.append((ACTION_DELTA, self._buf[:match.start()]))
                self._buf = self._buf[match.start():]
                self._holding = True
                # 落入候选判定
            resolved = self._resolve(final=final)
            if resolved is None:
                # 数据不足：流已结束或候选超长时放弃判定，按正文放行
                if final or len(self._buf) > self._max_hold:
                    out.append((ACTION_DELTA, self._buf))
                    self._buf = ""
                    self._holding = False
                return out
            consumed, actions = resolved
            out.extend(actions)
            self._buf = self._buf[consumed:]
            self._holding = False
            if consumed <= 0:  # 防御：绝不死循环
                out.append((ACTION_DELTA, self._buf))
                self._buf = ""
                return out
        return out

    def _resolve(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """判定候选缓冲；返回（消费长度, 动作列表），数据不足返回 None。"""
        kind = _kind_of(self._buf)
        if kind == "fence":
            return self._resolve_fence(final=final)
        if kind == "json":
            return self._resolve_json(final=final)
        if kind == "tag":
            return self._resolve_tag(final=final)
        if kind == "to_functions":
            return self._resolve_to_functions(final=final)
        if kind == "label":
            return self._resolve_label(final=final)
        # 未知标记：不拦截，原样放行
        return len(self._buf), [(ACTION_DELTA, self._buf)]

    def _resolve_json(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """行首裸 JSON：配对完整即判定，是否工具调用都消费到闭括号。"""
        start = self._buf.find("{")
        if start == -1:
            return None
        end = _bracket_end(self._buf, start, "{", "}")
        if end is None:
            return None
        consumed = end + 1
        calls = _parse_calls(self._buf[start:consumed])
        if calls:
            return consumed, [(ACTION_TOOL_CALL, c) for c in calls]
        return consumed, [(ACTION_DELTA, self._buf[:consumed])]

    def _resolve_fence(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """代码围栏：内容能解析成工具调用则整块吞掉，否则整块放行。"""
        open_match = _FENCE_OPEN_RE.match(self._buf)
        if open_match is None:
            return len(self._buf), [(ACTION_DELTA, self._buf)]
        content_start = open_match.end()
        if self._buf[content_start:content_start + 1] == "\n":
            content_start += 1
        close = _FENCE_CLOSE_RE.search(self._buf, content_start)
        if close is None:
            if not final:
                return None
            body = self._buf[content_start:]
            consumed = len(self._buf)
        else:
            body = self._buf[content_start:close.start()]
            consumed = close.end()
        calls = _parse_calls(body)
        if calls:
            return consumed, [(ACTION_TOOL_CALL, c) for c in calls]
        return consumed, [(ACTION_DELTA, self._buf[:consumed])]

    def _resolve_tag(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """特殊标记形态：等 JSON 与闭标签齐全再判定，成功则连闭标签一起吞掉。"""
        stripped = self._buf.lstrip(" \t")
        close_marker = next(
            (close for open_marker, close in _TAG_CLOSE if stripped.startswith(open_marker)), ""
        )
        start = self._buf.find("{")
        if start == -1:
            return None if not final else (len(self._buf), [(ACTION_DELTA, self._buf)])
        end = _bracket_end(self._buf, start, "{", "}")
        if end is None:
            return None if not final else (len(self._buf), [(ACTION_DELTA, self._buf)])
        calls = _parse_calls(self._buf[start:end + 1])
        if not calls:
            # 不是工具调用：示例代码等内容原样放行（含标记本身）
            return end + 1, [(ACTION_DELTA, self._buf[:end + 1])]
        if close_marker:
            close_idx = self._buf.find(close_marker, end + 1)
            if close_idx == -1 and not final:
                return None  # 等闭标签一起吞，避免残骸漏出
            if close_idx != -1:
                consumed = close_idx + len(close_marker)
                return consumed, [(ACTION_TOOL_CALL, c) for c in calls]
        return end + 1, [(ACTION_TOOL_CALL, c) for c in calls]

    def _resolve_to_functions(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """to=functions.名称 {参数} 伪协议：工具名来自标记，JSON 视为参数。"""
        name_match = _TO_FUNCTIONS_NAME_RE.search(self._buf)
        if name_match is None:
            return None if not final else (len(self._buf), [(ACTION_DELTA, self._buf)])
        name = name_match.group(1)
        start = self._buf.find("{", name_match.end())
        if start == -1 or start > name_match.end() + _LABEL_WINDOW:
            if not final and start == -1 and name_match.end() + _LABEL_WINDOW >= len(self._buf):
                return None  # 标记后暂时没内容，再等一点数据
            return len(self._buf), [(ACTION_DELTA, self._buf)]
        end = _bracket_end(self._buf, start, "{", "}")
        if end is None:
            return None if not final else (len(self._buf), [(ACTION_DELTA, self._buf)])
        consumed = end + 1
        data = _load_json_candidate(self._buf[start:consumed])
        call = None
        if data is not _MISSING and isinstance(data, dict):
            call = _normalize_call(data)
            if call is None and _CALL_NAME_RE.match(name):
                # 整个 JSON 就是参数（常见：to=functions.x {"city": "..."})
                call = {"id": "", "name": name,
                        "arguments": json.dumps(data, ensure_ascii=False)}
        if call:
            return consumed, [(ACTION_TOOL_CALL, call)]
        return consumed, [(ACTION_DELTA, self._buf[:consumed])]

    def _resolve_label(self, *, final: bool) -> tuple[int, list[tuple[str, Any]]] | None:
        """tool_call: 前缀形态：标记后窗口内的 JSON 判定为调用。"""
        start = self._buf.find("{")
        if start == -1 or start > _LABEL_WINDOW:
            if not final and start == -1 and len(self._buf) < _LABEL_WINDOW:
                return None
            return len(self._buf), [(ACTION_DELTA, self._buf)]
        end = _bracket_end(self._buf, start, "{", "}")
        if end is None:
            return None if not final else (len(self._buf), [(ACTION_DELTA, self._buf)])
        consumed = end + 1
        calls = _parse_calls(self._buf[start:consumed])
        if calls:
            return consumed, [(ACTION_TOOL_CALL, c) for c in calls]
        return consumed, [(ACTION_DELTA, self._buf[:consumed])]
