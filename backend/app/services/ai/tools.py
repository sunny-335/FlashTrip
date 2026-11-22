"""AI 工具注册表：只读工具默认可用，写工具必须前端二次确认 + 权限校验。

- 只读：list_trips / get_plan / get_expenses / search_poi
- 写类：add_plan_item / move_plan_item / create_booking，走与人工操作同一套
  app.api.v1.deps.require_permission 判定（owner/admin 或 TripMember + Permission）。
- ai_tools_enabled=false 时任何 tool_call 一律返回 AI_TOOLS_DISABLED。
- tool_call 与 tool_result 均落 ai_audit_logs。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import DateTime, String, Text

from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.services.ai.audit import record
from app.services.map.poi_adapter import search_poi

_SKIP_COLUMNS = ("created_at", "updated_at", "deleted_at")

TOOL_DEFS: dict[str, dict[str, Any]] = {
    "list_trips": {
        "description": "列出当前用户可访问的行程（只读）",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_plan": {
        "description": "读取指定行程的行程安排条目（只读）",
        "parameters": {"type": "object", "properties": {"trip_id": {"type": "string"}}, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_expenses": {
        "description": "读取指定行程的费用记录（只读）",
        "parameters": {"type": "object", "properties": {"trip_id": {"type": "string"}}, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "search_poi": {
        "description": "按关键词搜索地点，返回已归一化为 WGS84 的 POI（只读）",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "搜索关键词"},
                "city": {"type": "string"},
                "provider": {"type": "string"},
            },
            "required": ["q"], "additionalProperties": False,
        },
        "write": False, "permission": None,
    },
    "add_plan_item": {
        "description": "新增一个行程安排条目（写操作，需前端确认，权限 plan:write）",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "name": {"type": "string"},
                "type": {"type": "string"}, "day_id": {"type": "string"},
                "bucket": {"type": "string"}, "sort_key": {"type": "string"},
                "lng": {"type": "number"}, "lat": {"type": "number"},
                "coord_system": {"type": "string"}, "note": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "write": True, "permission": "plan:write",
    },
    "move_plan_item": {
        "description": "移动/重排一个行程安排条目（写操作，需前端确认，权限 plan:write）",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"}, "day_id": {"type": "string"},
                "sort_key": {"type": "string"}, "bucket": {"type": "string"},
            },
            "required": ["item_id"], "additionalProperties": False,
        },
        "write": True, "permission": "plan:write",
    },
    "create_booking": {
        "description": "新增一条预订（写操作，需前端确认，权限 booking:write）",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string"}, "vendor": {"type": "string"},
                "booking_no": {"type": "string"}, "start_at": {"type": "string"},
                "end_at": {"type": "string"}, "amount": {"type": "number"},
                "currency": {"type": "string"}, "note": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "write": True, "permission": "booking:write",
    },
    # ---- 全站只读工具：覆盖预订 / 交通 / 行李 / 瞬间 / 分享 / 天气 ----
    "get_bookings": {
        "description": "读取指定行程的预订（机票/酒店/门票等）记录（只读）",
        "parameters": {"type": "object", "properties": {
            "trip_id": {"type": "string"}, "limit": {"type": "integer"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_transports": {
        "description": "读取指定行程的交通段落（只读）",
        "parameters": {"type": "object", "properties": {
            "trip_id": {"type": "string"}, "limit": {"type": "integer"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_packing": {
        "description": "读取指定行程的行李清单及条目（只读）",
        "parameters": {"type": "object", "properties": {
            "trip_id": {"type": "string"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_moments": {
        "description": "读取当前用户可见的旅途瞬间（本人全部 + 他人公开的，只读）",
        "parameters": {"type": "object", "properties": {
            "trip_id": {"type": "string"}, "limit": {"type": "integer"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_shares": {
        "description": "读取指定行程的公开分享链接列表（不含 token，只读）",
        "parameters": {"type": "object", "properties": {
            "trip_id": {"type": "string"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    "get_weather": {
        "description": "查询城市天气与出行建议（只读；未给 city 时用行程目的地）",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}, "days": {"type": "integer"},
            "provider": {"type": "string"},
        }, "additionalProperties": False},
        "write": False, "permission": None,
    },
    # ---- 全站写工具：均需前端二次确认 + 与人工相同的权限校验 ----
    "delete_trip": {
        "description": "删除（软删）当前行程，危险操作，需要用户回答是/否二次确认；权限 trip:settings",
        "parameters": {"type": "object", "properties": {
            "confirm": {"type": "string", "description": "用户二次确认，必须为 yes 才会执行"},
            "trip_id": {"type": "string"},
        }, "required": ["confirm"], "additionalProperties": False},
        "write": True, "permission": "trip:settings",
    },
    "rearrange_plan_times": {
        "description": "自动重排某一天计划项的时间以消除冲突（写操作，需前端确认，权限 plan:write）",
        "parameters": {"type": "object", "properties": {
            "day_id": {"type": "string"}, "use_ai": {"type": "boolean"},
        }, "required": ["day_id"], "additionalProperties": False},
        "write": True, "permission": "plan:write",
    },
    "set_moment_public": {
        "description": "设置某条旅途瞬间是否对外公开（写操作，需前端确认，权限 moment:write）",
        "parameters": {"type": "object", "properties": {
            "moment_id": {"type": "string"}, "is_public": {"type": "boolean"},
        }, "required": ["moment_id", "is_public"], "additionalProperties": False},
        "write": True, "permission": "moment:write",
    },
    "create_expense": {
        "description": "新增一条费用记录并自动分账（写操作，需前端确认，权限 expense:write）",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "category": {"type": "string"},
            "currency": {"type": "string"}, "note": {"type": "string"},
            "paid_by": {"type": "string"}, "occurred_at": {"type": "string"},
            "split_mode": {"type": "string"},
        }, "required": ["amount"], "additionalProperties": True},
        "write": True, "permission": "expense:write",
    },
}

READ_TOOLS = tuple(name for name, spec in TOOL_DEFS.items() if not spec["write"])
WRITE_TOOLS = tuple(name for name, spec in TOOL_DEFS.items() if spec["write"])


def _cfg(cfg: dict | None) -> dict:
    return cfg if cfg is not None else get_config_store().load()


def tools_enabled(cfg: dict | None = None) -> bool:
    """整体开关：优先读向导写入的 security.ai_tools_enabled，设置页可整体关闭。"""
    cfg = _cfg(cfg)
    ai = cfg.get("ai") or {}
    if "tools_enabled" in ai:
        return bool(ai["tools_enabled"])
    # 安装向导把总开关写在 security 段（权威位置）
    security = cfg.get("security") or {}
    if "ai_tools_enabled" in security:
        return bool(security["ai_tools_enabled"])
    prefs = cfg.get("preferences") or {}
    if "ai_tools_enabled" in prefs:
        return bool(prefs["ai_tools_enabled"])
    return True


def _tool_enabled(cfg: dict, name: str) -> bool:
    overrides = (cfg.get("ai") or {}).get("tool_overrides") or {}
    if name in overrides:
        return bool(overrides[name])
    return True


def _row_dict(row: Any) -> dict:
    """把 ORM 行按表列导出为可 JSON 序列化的字典（不依赖具体模型字段）。"""
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, bytes):
            continue
        out[column.name] = value
    return out


def _coerce_value(value: Any, column: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _coerce(model: Any, arguments: dict, extra: dict) -> dict:
    """只使用模型真实存在的列构造行，避免写工具依赖不确定的模型字段。"""
    columns = {c.name: c for c in model.__table__.columns}
    data: dict[str, Any] = {}
    for key, value in {**arguments, **extra}.items():
        if key in columns and key not in _SKIP_COLUMNS:
            data[key] = _coerce_value(value, columns[key])
    for name, column in columns.items():
        if name in data or name in _SKIP_COLUMNS:
            continue
        if not column.nullable and column.default is None and column.server_default is None:
            if isinstance(column.type, (String, Text)):
                data[name] = ""
    return data


def _limit_arg(args: dict, default: int = 100) -> int:
    """安全解析工具参数里的 limit，避免非法值把对话打成 500。"""
    try:
        return max(1, min(int(args.get("limit") or default), 200))
    except (TypeError, ValueError):
        return default


def _query(db, model, where: dict, limit: int) -> list[dict]:
    columns = {c.name for c in model.__table__.columns}
    query = db.query(model)
    for key, value in where.items():
        if key in columns:
            query = query.filter(getattr(model, key) == value)
    return [_row_dict(row) for row in query.limit(limit).all()]


class ToolRegistry:
    def __init__(self, cfg: dict | None = None, db=None, user=None, trip_id: str | None = None) -> None:
        self.cfg = _cfg(cfg)
        self.db = db
        self.user = user
        self.trip_id = trip_id

    @staticmethod
    def config(cfg: dict | None = None) -> dict:
        """GET /ai/tools：工具清单与开关状态（不含任何密钥）。"""
        cfg = _cfg(cfg)
        return {
            "enabled": tools_enabled(cfg),
            "requiresConfirmation": True,
            "readTools": [n for n in READ_TOOLS if _tool_enabled(cfg, n)],
            "writeTools": [n for n in WRITE_TOOLS if _tool_enabled(cfg, n)],
            "tools": [
                {
                    "name": name,
                    "description": spec["description"],
                    "write": spec["write"],
                    "permission": spec["permission"],
                    "enabled": _tool_enabled(cfg, name) and tools_enabled(cfg),
                }
                for name, spec in TOOL_DEFS.items()
            ],
        }

    @staticmethod
    def set_config(payload: dict) -> dict:
        """PUT /ai/tools/config：整体开关 + 单工具覆盖，写入 config.json（原子写）。"""
        store = get_config_store()
        cfg = store.load()
        ai = dict(cfg.get("ai") or {})
        if "enabled" in payload:
            enabled = bool(payload["enabled"])
            ai["tools_enabled"] = enabled
            # 与向导的 security.ai_tools_enabled 保持双写一致
            security = dict(cfg.get("security") or {})
            security["ai_tools_enabled"] = enabled
            cfg["security"] = security
        tools = payload.get("tools")
        if isinstance(tools, dict):
            overrides = dict(ai.get("tool_overrides") or {})
            for name, enabled in tools.items():
                if name in TOOL_DEFS:
                    overrides[name] = bool(enabled)
            ai["tool_overrides"] = overrides
        cfg["ai"] = ai
        store.save(cfg)
        return ToolRegistry.config(cfg)

    def definitions(self) -> list[dict]:
        """OpenAI tools 参数；工具整体关闭时返回空列表（模型不会产生 tool_call）。"""
        if not tools_enabled(self.cfg):
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
            for name, spec in TOOL_DEFS.items()
            if _tool_enabled(self.cfg, name)
        ]

    def _assert_permission(self, key: str) -> None:
        """复用与人工写端点完全相同的 require_permission 依赖。"""
        from app.api.v1.deps import require_permission

        if not self.trip_id:
            raise AppError(ErrorCode.FORBIDDEN, "缺少行程上下文，无法执行写工具")
        dependency = require_permission(key)
        # 显式传入 db/user 覆盖 Depends，path_params 提供统一的 trip_id
        fake_request = SimpleNamespace(path_params={"trip_id": self.trip_id})
        dependency(request=fake_request, db=self.db, user=self.user)

    def execute(self, name: str, arguments: Any = None, *, confirmed: bool = False) -> dict:
        """执行单个工具；写工具未确认时返回 needConfirm，由前端弹确认卡后重放。"""
        if not tools_enabled(self.cfg):
            raise AppError(ErrorCode.AI_TOOLS_DISABLED, "AI 工具已在设置中关闭")
        spec = TOOL_DEFS.get(name)
        if spec is None:
            raise AppError(ErrorCode.VALIDATION, f"未知工具：{name}")
        if not _tool_enabled(self.cfg, name):
            raise AppError(ErrorCode.AI_TOOLS_DISABLED, f"工具 {name} 已被禁用")
        args = arguments or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}

        user_id = getattr(self.user, "id", None) if self.user is not None else None
        record(self.db, user_id=user_id, trip_id=self.trip_id, action="tool_call",
               payload={"tool": name, "arguments": args, "confirmed": bool(confirmed)})

        if spec["write"] and not confirmed:
            return {
                "needConfirm": True,
                "tool": name,
                "arguments": args,
                "permission": spec["permission"],
                "message": "该操作会修改行程数据，请在前端确认后执行",
            }
        if spec["write"]:
            self._assert_permission(spec["permission"])

        result = self._dispatch(name, args)
        record(self.db, user_id=user_id, trip_id=self.trip_id, action="tool_result",
               payload={"tool": name, "arguments": args, "result": result})
        return {"tool": name, "result": result}

    def _dispatch(self, name: str, args: dict) -> Any:
        db = self.db
        if db is None:
            raise AppError(ErrorCode.INTERNAL, "工具执行缺少数据库会话")
        trip_id = args.get("trip_id") or self.trip_id

        if name == "list_trips":
            from app.models.trip import Trip

            user_id = getattr(self.user, "id", None)
            return _query(db, Trip, {"owner_id": user_id}, int(args.get("limit") or 20))

        if name == "get_plan":
            from app.models.plan import PlanItem

            return _query(db, PlanItem, {"trip_id": trip_id}, 100)

        if name == "get_expenses":
            from app.models.expense import Expense

            return _query(db, Expense, {"trip_id": trip_id}, 100)

        if name == "search_poi":
            q = str(args.get("q") or "").strip()
            if not q:
                raise AppError(ErrorCode.VALIDATION, "搜索关键词不能为空")
            pois = search_poi(q, provider=args.get("provider"), city=str(args.get("city") or ""), cfg=self.cfg)
            return pois[:10]

        # ------------------------------------------------ 全站只读工具
        if name == "get_bookings":
            from app.models.booking import Booking

            return _query(db, Booking, {"trip_id": trip_id}, _limit_arg(args))

        if name == "get_transports":
            from app.models.transport import Transport

            return _query(db, Transport, {"trip_id": trip_id}, _limit_arg(args))

        if name == "get_packing":
            from app.models.packing import PackingItem, PackingList

            lists = (
                db.query(PackingList)
                .filter(PackingList.trip_id == trip_id)
                .order_by(PackingList.sort_key)
                .all()
            )
            out: list[dict] = []
            for packing_list in lists:
                items = (
                    db.query(PackingItem)
                    .filter(PackingItem.list_id == packing_list.id)
                    .order_by(PackingItem.sort_key)
                    .all()
                )
                out.append({
                    "list": {"id": packing_list.id, "name": packing_list.name},
                    "items": [
                        {"id": item.id, "name": item.name,
                         "qty": int(item.qty or 1), "checked": bool(item.checked),
                         "assignee_id": item.assignee_id}
                        for item in items
                    ],
                })
            return out

        if name == "get_moments":
            from sqlalchemy import or_

            from app.models.moment import Moment

            viewer_id = getattr(self.user, "id", None)
            query = db.query(Moment).filter(Moment.trip_id == trip_id)
            if viewer_id:
                query = query.filter(
                    or_(Moment.author_id == viewer_id, Moment.is_public.is_(True))
                )
            else:
                query = query.filter(Moment.is_public.is_(True))
            return [
                _row_dict(row)
                for row in query.order_by(Moment.taken_at.desc()).limit(_limit_arg(args)).all()
            ]

        if name == "get_shares":
            from app.services import share_service

            return share_service.list_shares(db, trip_id) if trip_id else []

        if name == "get_weather":
            from app.services import weather_service

            city = str(args.get("city") or "").strip()
            if not city and trip_id:
                from app.models.trip import Trip

                trip = db.get(Trip, trip_id)
                city = str(getattr(trip, "destination", None) or "").strip()
            if not city:
                raise AppError(ErrorCode.VALIDATION, "请提供城市名称或为行程设置目的地")
            try:
                return weather_service.fetch_weather(
                    city,
                    days=int(args.get("days") or 7),
                    provider=args.get("provider") or None,
                    db=db,
                )
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001  天气不可用降级为可读提示，不打断对话
                return {"ok": False, "city": city,
                        "message": f"天气服务暂不可用：{type(exc).__name__}"}

        if name == "add_plan_item":
            from app.models.plan import PlanItem

            data = _coerce(PlanItem, args, {"trip_id": trip_id, "id": new_id()})
            if "title" in data and not data["title"] and args.get("name"):
                data["title"] = str(args["name"])
            item = PlanItem(**data)
            db.add(item)
            db.commit()
            return _row_dict(item)

        if name == "move_plan_item":
            from app.models.plan import PlanItem

            item = db.get(PlanItem, str(args.get("item_id") or ""))
            if item is None:
                raise AppError(ErrorCode.NOT_FOUND, "行程条目不存在")
            if trip_id and getattr(item, "trip_id", None) not in (None, trip_id):
                raise AppError(ErrorCode.FORBIDDEN, "该条目不属于当前行程")
            for key in ("day_id", "sort_key", "bucket"):
                if key in args and hasattr(PlanItem, key):
                    setattr(item, key, args[key])
            db.commit()
            return _row_dict(item)

        if name == "create_booking":
            from app.models.booking import Booking

            data = _coerce(Booking, args, {"trip_id": trip_id, "id": new_id()})
            booking = Booking(**data)
            db.add(booking)
            db.commit()
            return _row_dict(booking)

        # ------------------------------------------------ 全站写工具（真实 DB 副作用）
        if name == "delete_trip":
            from datetime import datetime, timezone

            from app.models.trip import Trip

            confirm = str(args.get("confirm") or "").strip().lower()
            if confirm not in ("yes", "y", "true", "1", "是"):
                raise AppError(
                    ErrorCode.VALIDATION,
                    "删除行程需要用户回答是/否二次确认（confirm 必须为 yes）",
                )
            target = str(args.get("trip_id") or self.trip_id or "")
            if not target:
                raise AppError(ErrorCode.VALIDATION, "缺少行程上下文，无法删除行程")
            if self.trip_id and target != self.trip_id:
                raise AppError(ErrorCode.FORBIDDEN, "不允许删除当前上下文之外的行程")
            trip = db.get(Trip, target)
            if trip is None:
                raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
            trip.deleted_at = datetime.now(timezone.utc)
            db.commit()
            return {"id": target, "deleted": True, "title": trip.title}

        if name == "rearrange_plan_times":
            from app.services import plan_service

            day_id = str(args.get("day_id") or "") or None
            return plan_service.auto_arrange(
                db, trip_id, day_id, use_ai=bool(args.get("use_ai"))
            )

        if name == "set_moment_public":
            from app.models.moment import Moment

            moment = db.get(Moment, str(args.get("moment_id") or ""))
            if moment is None or (trip_id and moment.trip_id != trip_id):
                raise AppError(ErrorCode.NOT_FOUND, "瞬间记录不存在")
            moment.is_public = bool(args.get("is_public"))
            db.commit()
            return _row_dict(moment)

        if name == "create_expense":
            from app.models.expense import Expense
            from app.models.trip import Trip
            from app.services import expense_service

            if args.get("amount") is None:
                raise AppError(ErrorCode.VALIDATION, "费用金额不能为空")
            data = _coerce(Expense, args, {"trip_id": trip_id, "id": new_id()})
            expense = Expense(**data)
            db.add(expense)
            db.flush()
            trip = db.get(Trip, trip_id) if trip_id else None
            if trip is not None:
                # 复用人工侧同一套分账逻辑，保证金额与明细自洽
                try:
                    expense_service.normalize_split(expense, trip)
                except AppError:
                    raise
                except Exception:  # noqa: BLE001  分账异常不阻断费用落库
                    pass
            db.commit()
            return _row_dict(expense)

        raise AppError(ErrorCode.VALIDATION, f"工具 {name} 未实现")
