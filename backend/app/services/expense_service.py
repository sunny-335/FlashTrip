"""多人智能分账服务。

分账模式 split_mode：
  equal      按有效人数均摊（含儿童，每人一份）
  child_free 儿童免账，仅成人分摊
  family     以家庭为单位按家庭数分摊，家庭内成员均分
  custom     使用传入的 shares 作为权重，并校验金额合计
  payer_only 仅记垫付人：整笔金额记在垫付人名下，不向其他成员分摊

split_json 与 split_detail_json 复用同一明细结构：
  {"participants":[{"id","name","is_child","family"}, ...],
   "shares":[{"participant_id","share","amount"}, ...],
   "child_free":bool, "note":str}

金额一律用 Decimal 计算并 quantize(0.01)；按权重比例分配时把尾差归入
最后一位参与者，保证每笔分账合计精确等于费用金额。
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.models.expense import Expense
from app.models.trip import Trip

CENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
SPLIT_MODES = ("equal", "child_free", "family", "custom", "payer_only")
# 费用未记录垫付人时，为保持「每笔金额都有人垫付」的账目平衡使用的占位 id
UNASSIGNED_ID = "__unassigned__"


# ---------------------------------------------------------------- 基础工具

def _dec(value: Any) -> Decimal:
    """任意数值 -> Decimal（经 str 中转，避免二进制浮点误差）。"""
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def _q(value: Any) -> Decimal:
    """金额 -> Decimal 并量化到分。"""
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_jsonable(value: Any) -> Any:
    """递归把明细中的 Decimal 转成 JSON 安全的 float（金额已量化到分）。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _dump_detail(detail: dict) -> str:
    return json.dumps(to_jsonable(detail), ensure_ascii=False)


def _load_detail(expense: Any) -> dict:
    """优先读 split_detail_json，回落 split_json；兼容旧结构 / 损坏数据。"""
    for attr in ("split_detail_json", "split_json"):
        raw = getattr(expense, attr, None)
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data:
            return data
    return {}


# ---------------------------------------------------------------- 参与者

def auto_participants(trip: Any) -> list[dict]:
    """按行程人数自动生成匿名参与者：成员 1..N，末 children_count 位标记为儿童。

    家庭分组：以成人数量为家庭数，成人各领一个家庭（A/B/C...），
    儿童按轮转挂到各家庭，保证每个家庭至少有一位成人。
    """
    n = max(1, int(getattr(trip, "traveler_count", 1) or 1))
    children = max(0, int(getattr(trip, "children_count", 0) or 0))
    children = min(children, n - 1)  # 至少保留 1 位成人
    adults = n - children
    family_count = max(1, adults)
    out: list[dict] = []
    for i in range(n):
        group = i % family_count
        label = chr(ord("A") + group) if group < 26 else f"F{group + 1}"
        out.append({
            "id": f"p{i + 1}",
            "name": f"成员 {i + 1}",
            "is_child": i >= adults,
            "family": label,
        })
    return out


def _resolve_participants(trip: Any, detail: dict) -> list[dict]:
    """请求体显式给 participants 时以其为准，否则按行程人数自动生成。"""
    raw = detail.get("participants")
    if isinstance(raw, list) and raw:
        out: list[dict] = []
        for i, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                continue
            out.append({
                "id": str(item.get("id") or f"p{i}"),
                "name": str(item.get("name") or f"成员 {i}"),
                "is_child": bool(item.get("is_child", item.get("isChild", False))),
                "family": str(item.get("family") or ""),
            })
        if out:
            return out
    return auto_participants(trip)


# ---------------------------------------------------------------- 份额权重

def _weights(participants: list[dict], mode: str, detail: dict) -> dict[str, Decimal]:
    """按模式给出每位参与者的相对份额权重（非金额，可为小数）。"""
    ids = [p["id"] for p in participants]
    if mode == "payer_only":
        payer = str(detail.get("payer_id") or "")
        target = payer if payer in ids else (ids[0] if ids else "")
        return {pid: (ONE if pid == target else ZERO) for pid in ids}
    if mode == "custom":
        raw = detail.get("shares")
        if isinstance(raw, list) and raw:
            out = {pid: ZERO for pid in ids}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("participant_id") or item.get("id") or "")
                if pid not in out:
                    continue
                # 允许只给 amount 不显式给 share：以金额作为权重
                raw_weight = item.get("share") if item.get("share") is not None else item.get("amount")
                weight = _dec(raw_weight)
                out[pid] = weight if weight > 0 else ZERO
            return out
        return {pid: ONE for pid in ids}
    if mode == "family":
        groups: dict[str, list[str]] = {}
        for p in participants:
            key = str(p.get("family") or p["id"])
            groups.setdefault(key, []).append(p["id"])
        out = {pid: ZERO for pid in ids}
        for members in groups.values():
            unit = ONE / Decimal(len(members))
            for pid in members:
                out[pid] = unit
        return out
    # equal / child_free：成人每人一份，儿童由调用方按需置零
    return {pid: ONE for pid in ids}


def _allocate(total: Decimal, ids: list[str], weights: dict[str, Decimal]) -> list[dict]:
    """按权重比例分配金额；尾差归入最后一位**有效份额**参与者，保证合计精确等于 total。

    零权重参与者（如 child_free 下的儿童、payer_only 下的其他成员）始终为 0，
    尾差只落到最后一个正权重者，避免儿童被误分配金额。
    """
    if not ids:
        return []
    total_w = sum((weights.get(pid, ZERO) for pid in ids), ZERO)
    if total_w <= 0:
        weights = {pid: ONE for pid in ids}
        total_w = Decimal(len(ids))
    positive = [k for k, pid in enumerate(ids) if weights.get(pid, ZERO) > 0]
    last_effective = positive[-1] if positive else len(ids) - 1
    out: list[dict] = []
    allocated = ZERO
    for k, pid in enumerate(ids):
        weight = weights.get(pid, ZERO)
        if k == last_effective:
            # 尾差归入最后一位有效份额者
            value = (total - allocated).quantize(CENT, rounding=ROUND_HALF_UP)
        elif weight <= 0:
            value = ZERO
        else:
            value = (total * weight / total_w).quantize(CENT, rounding=ROUND_HALF_UP)
            allocated += value
        out.append({
            "participant_id": pid,
            "share": float(weight),
            "amount": value,  # Decimal，供调用方精确求和
        })
    return out


def compute_shares(amount: Any, mode: str, trip: Any, detail: dict | None = None) -> list[dict]:
    """计算单笔费用的分账明细。

    返回 [{"participant_id","share","amount"}, ...]，其中 amount 为已量化到分的
    Decimal；所有 amount 之和精确等于量化后的 amount。
    """
    total = _q(amount)
    detail = dict(detail or {})
    mode = mode if mode in SPLIT_MODES else "equal"
    participants = _resolve_participants(trip, detail)
    ids = [p["id"] for p in participants]
    child_free = (mode == "child_free") or bool(detail.get("child_free"))

    # 自定义模式：传入了显式金额时必须与费用金额合计一致
    if mode == "custom":
        raw = detail.get("shares")
        if isinstance(raw, list) and raw:
            explicit = [
                _q(item.get("amount"))
                for item in raw
                if isinstance(item, dict) and item.get("amount") is not None
            ]
            if explicit and sum(explicit, ZERO) != total:
                raise AppError(ErrorCode.VALIDATION, "自定义分账金额合计与费用金额不一致")

    weights = _weights(participants, mode, detail)
    if child_free:
        # 儿童免账：儿童份额一律为 0
        for p in participants:
            if p.get("is_child"):
                weights[p["id"]] = ZERO
    # 全为 0（例如没有有效成人）时退化为均摊，保证金额始终有归属
    if sum(weights.values(), ZERO) <= 0:
        weights = {pid: ONE for pid in ids}
    return _allocate(total, ids, weights)


# ---------------------------------------------------------------- 归一化落库

def normalize_split(expense: Any, trip: Any) -> dict:
    """按 expense.split_mode / 金额与行程人数生成完整明细，并写回三列。

    写回：split_json、split_detail_json（统一结构）、split_mode。
    返回明细 dict（其中 shares[*].amount 为 Decimal）。
    """
    detail = _load_detail(expense)
    mode = getattr(expense, "split_mode", None) or detail.get("mode") or "equal"
    if mode not in SPLIT_MODES:
        mode = "equal"
    detail["payer_id"] = getattr(expense, "paid_by", None) or detail.get("payer_id") or ""
    participants = _resolve_participants(trip, detail)
    shares = compute_shares(getattr(expense, "amount", 0), mode, trip, detail)
    out: dict = {
        "participants": participants,
        "shares": shares,
        "child_free": bool(detail.get("child_free") or mode == "child_free"),
        "note": str(detail.get("note") or ""),
    }
    text = _dump_detail(out)
    expense.split_json = text
    expense.split_detail_json = text
    expense.split_mode = mode
    return out


def apply_split(expense: Any, trip: Any, body: dict) -> dict:
    """处理 POST /expenses/{id}/split：合并请求体 -> 重算 -> 落库。"""
    mode = str(body.get("split_mode") or body.get("splitMode") or getattr(expense, "split_mode", None) or "equal")
    if mode not in SPLIT_MODES:
        raise AppError(ErrorCode.VALIDATION, "不支持的分账方式")
    detail = _load_detail(expense)
    detail["mode"] = mode
    child_free = body.get("child_free", body.get("childFree"))
    detail["child_free"] = bool(child_free) if child_free is not None else bool(detail.get("child_free") or mode == "child_free")
    if body.get("note") is not None:
        detail["note"] = str(body["note"])
    else:
        detail.setdefault("note", "")
    if body.get("participants") is not None:
        detail["participants"] = body["participants"]
    if body.get("shares") is not None:
        detail["shares"] = body["shares"]
    detail["payer_id"] = getattr(expense, "paid_by", None) or ""
    expense.split_mode = mode
    # 先把请求体种子写入明细列，normalize_split 据此重算并覆盖为最终结构
    expense.split_detail_json = _dump_detail(detail)
    return normalize_split(expense, trip)


# ---------------------------------------------------------------- 汇总

def _ensure(info: dict, paid: dict, owed: dict, pid: str, name: str | None = None) -> None:
    if pid not in info:
        info[pid] = {"id": pid, "name": name or pid, "is_child": False, "family": ""}
        paid[pid] = ZERO
        owed[pid] = ZERO


def _safe_shares(expense: Any, trip: Any) -> list[dict]:
    """汇总用：优先用已落库的合规划分，否则重算；异常一律降级为均摊。"""
    amount = _q(getattr(expense, "amount", 0))
    detail = _load_detail(expense)
    mode = getattr(expense, "split_mode", None) or "equal"
    if mode not in SPLIT_MODES:
        mode = "equal"
    detail["payer_id"] = getattr(expense, "paid_by", None) or ""
    stored = detail.get("shares")
    if isinstance(stored, list) and stored:
        ssum = sum(
            (_q(item.get("amount")) for item in stored if isinstance(item, dict)),
            ZERO,
        )
        if ssum == amount:
            return [
                {"participant_id": str(item.get("participant_id") or ""), "amount": _q(item.get("amount"))}
                for item in stored
                if isinstance(item, dict) and item.get("participant_id")
            ]
    try:
        return compute_shares(amount, mode, trip, detail)
    except AppError:
        return compute_shares(amount, "equal", trip, {})


def _suggest_transfers(participants: list[dict]) -> list[dict]:
    """简单贪心：把负债者（balance<0）匹配给应收者（balance>0）。"""
    creditors = [[p["id"], _q(p["balance"])] for p in participants if _q(p["balance"]) > 0]
    debtors = [[p["id"], -_q(p["balance"])] for p in participants if _q(p["balance"]) < 0]
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)
    out: list[dict] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1]).quantize(CENT)
        if amount > 0:
            out.append({"from": debtors[i][0], "to": creditors[j][0], "amount": float(amount)})
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] <= 0:
            i += 1
        if creditors[j][1] <= 0:
            j += 1
    return out


def split_summary(db, trip_id: str) -> dict:
    """行程级分账汇总：垫付、应摊、余额与建议转账。

    balance = paid - owed（正=应收回，负=应付出）；participants 的 balance
    之和恒为 0，suggestedTransfers 可把全部负债结清。
    """
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    rows = db.query(Expense).filter(Expense.trip_id == trip_id).all()

    info: dict[str, dict] = {}
    paid: dict[str, Decimal] = {}
    owed: dict[str, Decimal] = {}
    for meta in auto_participants(trip):
        _ensure(info, paid, owed, meta["id"])
        info[meta["id"]].update(meta)

    total = ZERO
    payer_total = ZERO
    child_free = False
    for expense in rows:
        amount = _q(getattr(expense, "amount", 0))
        mode = getattr(expense, "split_mode", None) or "equal"
        if mode == "child_free" or _load_detail(expense).get("child_free"):
            child_free = True
        for share in _safe_shares(expense, trip):
            pid = str(share.get("participant_id") or "")
            if not pid:
                continue
            _ensure(info, paid, owed, pid)
            owed[pid] += _q(share.get("amount"))
        payer = str(getattr(expense, "paid_by", None) or "").strip() or UNASSIGNED_ID
        _ensure(info, paid, owed, payer, name="未指定垫付人" if payer == UNASSIGNED_ID else payer)
        paid[payer] += amount
        total += amount
        if payer != UNASSIGNED_ID:
            payer_total += amount

    participants: list[dict] = []
    for pid, meta in info.items():
        p = _q(paid[pid])
        o = _q(owed[pid])
        participants.append({
            "id": pid,
            "name": meta["name"],
            "is_child": bool(meta.get("is_child")),
            "family": str(meta.get("family") or ""),
            "paid": float(p),
            "owed": float(o),
            "balance": float((p - o).quantize(CENT, rounding=ROUND_HALF_UP)),
        })
    return {
        "total": float(total.quantize(CENT)),
        "payerTotal": float(payer_total.quantize(CENT)),
        "participants": participants,
        "suggestedTransfers": _suggest_transfers(participants),
        "travelerCount": int(getattr(trip, "traveler_count", 1) or 1),
        "childrenCount": int(getattr(trip, "children_count", 0) or 0),
        "childFree": child_free,
    }


def dominant_split_mode(db, trip_id: str) -> str:
    """summary 端点用：行程内出现次数最多的分账模式，无费用时默认 equal。"""
    counts: dict[str, int] = {}
    for row in db.query(Expense).filter(Expense.trip_id == trip_id).all():
        mode = getattr(row, "split_mode", None) or "equal"
        if mode in SPLIT_MODES:
            counts[mode] = counts.get(mode, 0) + 1
    return max(counts, key=counts.get) if counts else "equal"


def summary_extras(db, trip_id: str) -> dict:
    """GET /expenses/summary 在原有字段上追加的分账维度（不破坏前端）。"""
    summary = split_summary(db, trip_id)
    return {
        "splitMode": dominant_split_mode(db, trip_id),
        "participants": summary["participants"],
        "byParticipant": {p["id"]: p["owed"] for p in summary["participants"]},
    }
