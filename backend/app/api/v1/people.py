"""家庭 / 常用人员 / 行程参与人 API。

家庭与常用人员是用户级数据（按登录用户 owner_id 隔离）；行程参与人为 trip 级，
支持从常用人员或家庭一键带入多人，并同步行程人数。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission, require_user
from app.core.response import ok
from app.schemas.common import dump, dump_many
from app.schemas.people import (
    FrequentTravelerCreate,
    FrequentTravelerOut,
    FrequentTravelerUpdate,
    HouseholdCreate,
    HouseholdMemberCreate,
    HouseholdMemberOut,
    HouseholdMemberUpdate,
    HouseholdOut,
    HouseholdUpdate,
    TripParticipantOut,
    TripParticipantsIn,
    TripParticipantQuickAddIn,
)
from app.services import people_service

router = APIRouter(tags=["people"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _household_view(db: Session, household) -> dict:
    data = dump(HouseholdOut, household)
    data["members"] = dump_many(HouseholdMemberOut, people_service.list_members(db, household.id))
    return data


# ---------------------------------------------------------------- 家庭

@router.get("/households")
def list_households(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    rows = people_service.list_households(db, user.id)
    return ok([_household_view(db, row) for row in rows], request_id=_rid(request))


@router.post("/households")
def create_household(
    payload: HouseholdCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    household = people_service.create_household(db, user.id, payload)
    return ok(_household_view(db, household), request_id=_rid(request))


@router.get("/households/{household_id}")
def get_household(
    household_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    household, members = people_service.get_household(db, user.id, household_id)
    data = dump(HouseholdOut, household)
    data["members"] = dump_many(HouseholdMemberOut, members)
    return ok(data, request_id=_rid(request))


@router.put("/households/{household_id}")
def update_household(
    household_id: str,
    payload: HouseholdUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    household = people_service.update_household(db, user.id, household_id, payload)
    return ok(_household_view(db, household), request_id=_rid(request))


@router.delete("/households/{household_id}")
def delete_household(
    household_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    people_service.delete_household(db, user.id, household_id)
    return ok({"deleted": household_id}, request_id=_rid(request))


@router.post("/households/{household_id}/members")
def add_member(
    household_id: str,
    payload: HouseholdMemberCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """添加家庭成员；body 传 frequent_traveler_id 即可把常用人员加入家庭。"""
    member = people_service.add_member(db, user.id, household_id, payload)
    return ok(dump(HouseholdMemberOut, member), request_id=_rid(request))


@router.put("/households/{household_id}/members/{member_id}")
def update_member(
    household_id: str,
    member_id: str,
    payload: HouseholdMemberUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    member = people_service.update_member(db, user.id, household_id, member_id, payload)
    return ok(dump(HouseholdMemberOut, member), request_id=_rid(request))


@router.delete("/households/{household_id}/members/{member_id}")
def delete_member(
    household_id: str,
    member_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    people_service.delete_member(db, user.id, household_id, member_id)
    return ok({"deleted": member_id}, request_id=_rid(request))


# ---------------------------------------------------------------- 常用人员

@router.get("/frequent-travelers")
def list_frequent_travelers(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    rows = people_service.list_frequent(db, user.id)
    return ok(dump_many(FrequentTravelerOut, rows), request_id=_rid(request))


@router.post("/frequent-travelers")
def create_frequent_traveler(
    payload: FrequentTravelerCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    row = people_service.create_frequent(db, user.id, payload)
    return ok(dump(FrequentTravelerOut, row), request_id=_rid(request))


@router.put("/frequent-travelers/{traveler_id}")
def update_frequent_traveler(
    traveler_id: str,
    payload: FrequentTravelerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    row = people_service.update_frequent(db, user.id, traveler_id, payload)
    return ok(dump(FrequentTravelerOut, row), request_id=_rid(request))


@router.delete("/frequent-travelers/{traveler_id}")
def delete_frequent_traveler(
    traveler_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    people_service.delete_frequent(db, user.id, traveler_id)
    return ok({"deleted": traveler_id}, request_id=_rid(request))


# ---------------------------------------------------------------- 行程参与人

def _participants_view(rows: list) -> list[dict]:
    return dump_many(TripParticipantOut, rows)


@router.get("/trips/{trip_id}/participants")
def list_participants(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    rows = people_service.list_participants(db, trip_id)
    return ok(_participants_view(rows), request_id=_rid(request))


@router.post("/trips/{trip_id}/participants")
def add_participants(
    trip_id: str,
    payload: TripParticipantsIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    """手动批量添加参与人，并同步行程人数/儿童数。"""
    created, trip = people_service.add_participants(db, trip_id, payload.participants)
    return ok(
        {
            "created": _participants_view(created),
            "traveler_count": trip.traveler_count,
            "children_count": trip.children_count,
            "has_children": trip.has_children,
        },
        request_id=_rid(request),
    )


@router.post("/trips/{trip_id}/participants/quick-add")
def quick_add_participants(
    trip_id: str,
    payload: TripParticipantQuickAddIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    """从常用人员 / 家庭一键带入多人（同一来源重复带入自动跳过）。"""
    created, trip = people_service.quick_add(db, trip_id, user.id, payload)
    return ok(
        {
            "created": _participants_view(created),
            "traveler_count": trip.traveler_count,
            "children_count": trip.children_count,
            "has_children": trip.has_children,
        },
        request_id=_rid(request),
    )


@router.get("/trips/{trip_id}/participants/split")
def participants_for_split(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    """费用分账兼容结构：可直接作为费用 split 请求的 participants 字段。"""
    return ok(people_service.split_participants(db, trip_id), request_id=_rid(request))


@router.delete("/trips/{trip_id}/participants/{participant_id}")
def delete_participant(
    trip_id: str,
    participant_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    people_service.delete_participant(db, trip_id, participant_id)
    return ok({"deleted": participant_id}, request_id=_rid(request))
