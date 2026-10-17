import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models import AuditLog
from repositories.audit_logs import create_audit_log
from schemas.audit_logs import AuditLogOut, AuditLogPage
from services.audit_logs import (
    ActionType,
    get_company_log,
    list_company_logs,
    log_action,
    log_and_commit,
    sanitize,
)

START = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def page(db, user, **filters):
    options = {
        "action_type": None,
        "entity_type": None,
        "entity_id": None,
        "date_from": None,
        "date_to": None,
        "limit": 50,
        "offset": 0,
    }
    options.update(filters)
    return list_company_logs(db, user, **options)


@pytest.fixture
def fleet_logs(db_session, sample_fleet_user):
    match_id = uuid.uuid4()
    truck_id = uuid.uuid4()
    entries = []
    for minutes, action, entity_type, entity_id in (
        (0, ActionType.ASSESSMENT_REQUESTED, "match", match_id),
        (1, ActionType.ASSESSMENT_REQUESTED, "match", match_id),
        (2, ActionType.ASSESSMENT_REQUESTED, "match", match_id),
        (3, ActionType.FLEET_UPDATED, "truck", truck_id),
    ):
        entry = log_action(
            db_session,
            action,
            user=sample_fleet_user,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        entry.created_at = START + timedelta(minutes=minutes)
        entries.append(entry)
    db_session.commit()
    return {"match_id": match_id, "truck_id": truck_id, "entries": entries}


@pytest.fixture
def shipper_log(db_session, sample_user):
    entry = log_action(db_session, ActionType.SHIPMENT_PUBLISHED, user=sample_user)
    entry.created_at = START
    db_session.commit()
    return entry


def test_sanitize_redacts_secrets_at_any_depth():
    out = sanitize(
        {
            "password": "hunter2",
            "nested": {"api_key": "abc", "Authorization": "Bearer x", "ok": 1},
            "list": [{"access_token": "t"}],
            "amount": Decimal("10.50"),
            "id": uuid.UUID(int=1),
        }
    )
    assert out["password"] == "[REDACTED]"
    assert out["nested"] == {
        "api_key": "[REDACTED]",
        "Authorization": "[REDACTED]",
        "ok": 1,
    }
    assert out["list"] == [{"access_token": "[REDACTED]"}]
    assert out["amount"] == "10.50"
    assert out["id"] == str(uuid.UUID(int=1))


def test_log_action_uses_users_company(db_session, sample_user):
    entity_id = uuid.uuid4()
    entry = log_action(
        db_session,
        ActionType.SHIPMENT_PUBLISHED,
        user=sample_user,
        entity_type="shipment",
        entity_id=entity_id,
        details={"proposed_amount": Decimal("18500.00"), "token": "secret"},
    )
    db_session.commit()

    saved = db_session.query(AuditLog).filter(AuditLog.audit_id == entry.audit_id).one()
    assert saved.company_id == sample_user.company_id
    assert saved.user_id == sample_user.user_id
    assert saved.action_type == "shipment_published"
    assert saved.entity_id == entity_id
    assert saved.details == {"proposed_amount": "18500.00", "token": "[REDACTED]"}


def test_log_action_without_user(db_session, sample_fleet_company):
    entry = log_action(
        db_session,
        "verification_attempted",
        company_id=sample_fleet_company.company_id,
        details={"qr": "not found"},
    )
    db_session.commit()
    assert entry.user_id is None
    assert entry.company_id == sample_fleet_company.company_id


def test_log_is_rolled_back_with_failed_change(db_session, sample_fleet_user):
    log_action(db_session, ActionType.FLEET_UPDATED, user=sample_fleet_user)
    assert (
        db_session.query(AuditLog).filter_by(action_type="fleet_updated").count() == 1
    )

    db_session.rollback()

    assert (
        db_session.query(AuditLog).filter_by(action_type="fleet_updated").count() == 0
    )


def test_log_and_commit_saves_immediately(db_session, sample_fleet_user):
    log_and_commit(db_session, ActionType.AUTHORIZATION_FAILED, user=sample_fleet_user)
    assert (
        db_session.query(AuditLog).filter_by(action_type="authorization_failed").count()
        == 1
    )


def test_company_only_sees_its_own_logs(
    db_session, sample_fleet_user, sample_user, fleet_logs, shipper_log
):
    fleet_items, fleet_total = page(db_session, sample_fleet_user)
    shipper_items, shipper_total = page(db_session, sample_user)

    assert fleet_total == 4
    assert shipper_total == 1
    assert {e.company_id for e in fleet_items} == {sample_fleet_user.company_id}
    assert [e.audit_id for e in shipper_items] == [shipper_log.audit_id]


def test_filters(db_session, sample_fleet_user, fleet_logs):
    _, by_action = page(db_session, sample_fleet_user, action_type="fleet_updated")
    _, by_entity = page(db_session, sample_fleet_user, entity_id=fleet_logs["match_id"])
    _, by_type = page(db_session, sample_fleet_user, entity_type="truck")

    assert (by_action, by_entity, by_type) == (1, 3, 1)


def test_date_range_filter(db_session, sample_fleet_user, fleet_logs):
    items, total = page(
        db_session,
        sample_fleet_user,
        date_from=START + timedelta(minutes=1),
        date_to=START + timedelta(minutes=2),
    )
    assert total == 2
    assert [e.audit_id for e in items] == [
        fleet_logs["entries"][2].audit_id,
        fleet_logs["entries"][1].audit_id,
    ]


def test_newest_first_and_pagination(db_session, sample_fleet_user, fleet_logs):
    entries = fleet_logs["entries"]

    first, total = page(db_session, sample_fleet_user, limit=2)
    second, _ = page(db_session, sample_fleet_user, limit=2, offset=2)

    assert total == 4
    assert [e.audit_id for e in first] == [entries[3].audit_id, entries[2].audit_id]
    assert [e.audit_id for e in second] == [entries[1].audit_id, entries[0].audit_id]


def test_from_after_to_is_rejected(db_session, sample_fleet_user):
    with pytest.raises(HTTPException) as caught:
        page(
            db_session,
            sample_fleet_user,
            date_from=START,
            date_to=START - timedelta(days=1),
        )
    assert caught.value.status_code == 422


def test_get_single_entry_respects_company(
    db_session, sample_fleet_user, sample_user, fleet_logs
):
    audit_id = fleet_logs["entries"][0].audit_id

    assert get_company_log(db_session, sample_fleet_user, audit_id).audit_id == audit_id
    with pytest.raises(HTTPException) as caught:
        get_company_log(db_session, sample_user, audit_id)
    assert caught.value.status_code == 404


def test_unknown_entry_is_404(db_session, sample_fleet_user):
    with pytest.raises(HTTPException) as caught:
        get_company_log(db_session, sample_fleet_user, uuid.uuid4())
    assert caught.value.status_code == 404


def test_entries_fit_the_response_schema(db_session, sample_fleet_user, fleet_logs):
    items, total = page(db_session, sample_fleet_user, limit=2)

    result = AuditLogPage(
        items=[AuditLogOut.model_validate(e) for e in items],
        total=total,
        limit=2,
        offset=0,
    ).model_dump(mode="json")

    assert result["total"] == 4
    assert len(result["items"]) == 2
    first = result["items"][0]
    assert first["action_type"] == "fleet_updated"
    assert first["entity_type"] == "truck"
    assert first["company_id"] == str(sample_fleet_user.company_id)


def test_create_audit_log_saves_and_returns_entry(db_session, sample_user):
    entry = create_audit_log(
        db_session,
        user_id=sample_user.user_id,
        company_id=sample_user.company_id,
        action_type="verification_attempted",
        details={"qr": "matched"},
    )

    assert entry.audit_id is not None
    saved = db_session.query(AuditLog).filter(AuditLog.audit_id == entry.audit_id).one()
    assert saved.action_type == "verification_attempted"
    assert saved.details == {"qr": "matched"}
