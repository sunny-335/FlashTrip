"""家庭 / 常用人员 / 行程参与人服务。

- 家庭与常用人员为用户级数据，所有读写都按 owner_id 校验归属，越权按「不存在」处理；
- 家庭成员可直接添加，也可用 frequent_traveler_id 从常用人员库带入（记录来源）；
- 行程参与人支持从常用人员或家庭批量快速带入，并同步行程人数/儿童数（沿用 normalize_people 约束）；
- 行程参与人输出与费用分账的 participants 结构兼容，可直接用于分账请求。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.models.people import (
    FrequentTraveler,
    Household,
    HouseholdMember,
    TripParticipant,
)
from app.models.trip import Trip
from app.schemas.people import (
    FrequentTravelerCreate,
    FrequentTravelerUpdate,
    HouseholdCreate,
    HouseholdMemberCreate,
    HouseholdMemberUpdate,
    HouseholdUpdate,
    TripParticipantIn,
    TripParticipantQuickAddIn,
)


# ---------------------------------------------------------------- 归属查询

def _household_or_404(db: Session, owner_id: str, household_id: str) -> Household:
    row = db.get(Household, household_id)
    if row is None or row.owner_id != owner_id:
        raise AppError(ErrorCode.NOT_FOUND, "家庭不存在")
    return row


def _member_or_404(db: Session, household_id: str, member_id: str) -> HouseholdMember:
    row = db.get(HouseholdMember, member_id)
    if row is None or row.household_id != household_id:
        raise AppError(ErrorCode.NOT_FOUND, "家庭成员不存在")
    return row


def _frequent_or_404(db: Session, owner_id: str, traveler_id: str) -> FrequentTraveler:
    row = db.get(FrequentTraveler, traveler_id)
    if row is None or row.owner_id != owner_id:
        raise AppError(ErrorCode.NOT_FOUND, "常用人员不存在")
    return row


def _trip_or_404(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    return trip


# ---------------------------------------------------------------- 家庭

def list_households(db: Session, owner_id: str) -> list[Household]:
    return (
        db.query(Household)
        .filter(Household.owner_id == owner_id)
        .order_by(Household.created_at, Household.name)
        .all()
    )


def get_household(db: Session, owner_id: str,
                  household_id: str) -> tuple[Household, list[HouseholdMember]]:
    """家庭详情：返回家庭本体与其成员列表。"""
    household = _household_or_404(db, owner_id, household_id)
    return household, list_members(db, household.id)


def list_members(db: Session, household_id: str) -> list[HouseholdMember]:
    return (
        db.query(HouseholdMember)
        .filter(HouseholdMember.household_id == household_id)
        .order_by(HouseholdMember.created_at, HouseholdMember.name)
        .all()
    )


def _new_member(db: Session, owner_id: str, household_id: str,
                payload: HouseholdMemberCreate) -> HouseholdMember:
    """创建家庭成员；带 frequent_traveler_id 时以常用人员信息补全姓名/备注。"""
    name = str(payload.name or "").strip()
    note = payload.note
    frequent_id = (payload.frequent_traveler_id or "").strip() or None
    if frequent_id:
        freq = _frequent_or_404(db, owner_id, frequent_id)
        name = name or freq.name
        if note is None:
            note = freq.note
    if not name:
        raise AppError(ErrorCode.VALIDATION, "成员姓名不能为空")
    member = HouseholdMember(
        id=new_id(),
        household_id=household_id,
        name=name,
        is_child=bool(payload.is_child),
        note=note,
        frequent_traveler_id=frequent_id,
    )
    db.add(member)
    return member


def create_household(db: Session, owner_id: str, payload: HouseholdCreate) -> Household:
    household = Household(id=new_id(), owner_id=owner_id, name=payload.name, note=payload.note)
    db.add(household)
    for member_payload in payload.members or []:
        _new_member(db, owner_id, household.id, member_payload)
    db.commit()
    return household


def update_household(db: Session, owner_id: str, household_id: str,
                     payload: HouseholdUpdate) -> Household:
    household = _household_or_404(db, owner_id, household_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "name" and not str(value or "").strip():
            raise AppError(ErrorCode.VALIDATION, "家庭名称不能为空")
        setattr(household, key, value)
    db.commit()
    return household


def delete_household(db: Session, owner_id: str, household_id: str) -> None:
    """软删家庭及其成员，避免成员孤儿化后仍被家庭详情读到。"""
    household = _household_or_404(db, owner_id, household_id)
    now = datetime.now(timezone.utc)
    for member in list_members(db, household_id):
        member.deleted_at = now
    household.deleted_at = now
    db.commit()


def add_member(db: Session, owner_id: str, household_id: str,
               payload: HouseholdMemberCreate) -> HouseholdMember:
    _household_or_404(db, owner_id, household_id)
    member = _new_member(db, owner_id, household_id, payload)
    db.commit()
    return member


def update_member(db: Session, owner_id: str, household_id: str, member_id: str,
                  payload: HouseholdMemberUpdate) -> HouseholdMember:
    _household_or_404(db, owner_id, household_id)
    member = _member_or_404(db, household_id, member_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "name" and not str(value or "").strip():
            raise AppError(ErrorCode.VALIDATION, "成员姓名不能为空")
        setattr(member, key, value)
    db.commit()
    return member


def delete_member(db: Session, owner_id: str, household_id: str, member_id: str) -> None:
    _household_or_404(db, owner_id, household_id)
    member = _member_or_404(db, household_id, member_id)
    member.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------- 常用人员

def list_frequent(db: Session, owner_id: str) -> list[FrequentTraveler]:
    return (
        db.query(FrequentTraveler)
        .filter(FrequentTraveler.owner_id == owner_id)
        .order_by(FrequentTraveler.created_at, FrequentTraveler.name)
        .all()
    )


def create_frequent(db: Session, owner_id: str,
                    payload: FrequentTravelerCreate) -> FrequentTraveler:
    row = FrequentTraveler(id=new_id(), owner_id=owner_id, name=payload.name, note=payload.note)
    db.add(row)
    db.commit()
    return row


def update_frequent(db: Session, owner_id: str, traveler_id: str,
                    payload: FrequentTravelerUpdate) -> FrequentTraveler:
    row = _frequent_or_404(db, owner_id, traveler_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "name" and not str(value or "").strip():
            raise AppError(ErrorCode.VALIDATION, "常用人员姓名不能为空")
        setattr(row, key, value)
    db.commit()
    return row


def delete_frequent(db: Session, owner_id: str, traveler_id: str) -> None:
    row = _frequent_or_404(db, owner_id, traveler_id)
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------- 行程参与人

def list_participants(db: Session, trip_id: str) -> list[TripParticipant]:
    return (
        db.query(TripParticipant)
        .filter(TripParticipant.trip_id == trip_id)
        .order_by(TripParticipant.created_at, TripParticipant.name)
        .all()
    )


def _sync_trip_people(db: Session, trip: Trip, *, strict: bool = True) -> None:
    """把行程人数/儿童数与参与人列表对齐。

    strict=True（新增参与人）时若不满足「至少一位成人」则报错；
    strict=False（删除参与人）时规则冲突就保留原人数，避免删除操作被联动阻塞。
    """
    parts = list_participants(db, trip.id)
    total = len(parts)
    if total == 0:
        return
    children = sum(1 for p in parts if p.is_child)
    if children >= total:
        if strict:
            raise AppError(ErrorCode.VALIDATION, "至少需要一位成人参与人，儿童人数必须小于总人数")
        return
    trip.traveler_count = total
    trip.children_count = children
    trip.has_children = children > 0


def add_participants(db: Session, trip_id: str, items: list[TripParticipantIn],
                     *, source_type: str = "manual", source_id: str | None = None) -> tuple[list[TripParticipant], Trip]:
    """批量添加行程参与人（手动录入），并同步行程人数。"""
    trip = _trip_or_404(db, trip_id)
    created: list[TripParticipant] = []
    try:
        for item in items:
            name = str(item.name or "").strip()
            if not name:
                raise AppError(ErrorCode.VALIDATION, "参与人姓名不能为空")
            row = TripParticipant(
                id=new_id(),
                trip_id=trip_id,
                name=name,
                is_child=bool(item.is_child),
                family=str(item.family or ""),
                note=item.note,
                source_type=source_type,
                source_id=source_id,
            )
            db.add(row)
            created.append(row)
        db.flush()
        _sync_trip_people(db, trip, strict=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return created, trip


def quick_add(db: Session, trip_id: str, owner_id: str,
              payload: TripParticipantQuickAddIn) -> tuple[list[TripParticipant], Trip]:
    """从常用人员 / 家庭一键带入多人：同一来源重复带入时自动跳过。"""
    trip = _trip_or_404(db, trip_id)
    existing = {
        (p.source_type, p.source_id)
        for p in list_participants(db, trip_id)
        if p.source_id
    }
    created: list[TripParticipant] = []
    try:
        for traveler_id in payload.frequent_traveler_ids or []:
            freq = _frequent_or_404(db, owner_id, traveler_id)
            if ("frequent", freq.id) in existing:
                continue
            row = TripParticipant(
                id=new_id(),
                trip_id=trip_id,
                name=freq.name,
                is_child=False,
                family="",
                note=freq.note,
                source_type="frequent",
                source_id=freq.id,
            )
            db.add(row)
            created.append(row)
            existing.add(("frequent", freq.id))

        for household_id in payload.household_ids or []:
            household = _household_or_404(db, owner_id, household_id)
            for member in list_members(db, household.id):
                if ("household", member.id) in existing:
                    continue
                row = TripParticipant(
                    id=new_id(),
                    trip_id=trip_id,
                    name=member.name,
                    is_child=bool(member.is_child),
                    family=str(household.name or ""),
                    note=member.note,
                    source_type="household",
                    source_id=member.id,
                )
                db.add(row)
                created.append(row)
                existing.add(("household", member.id))

        db.flush()
        _sync_trip_people(db, trip, strict=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return created, trip


def delete_participant(db: Session, trip_id: str, participant_id: str) -> None:
    trip = _trip_or_404(db, trip_id)
    row = db.get(TripParticipant, participant_id)
    if row is None or row.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "行程参与人不存在")
    row.deleted_at = datetime.now(timezone.utc)
    db.flush()
    _sync_trip_people(db, trip, strict=False)
    db.commit()


def split_participants(db: Session, trip_id: str) -> list[dict]:
    """费用分账兼容结构，可直接作为 split 请求体的 participants。"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "is_child": bool(p.is_child),
            "family": p.family or "",
        }
        for p in list_participants(db, trip_id)
    ]
