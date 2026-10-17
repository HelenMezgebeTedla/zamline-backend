import uuid
from datetime import datetime, timedelta, timezone

import pytest

from security.tokens import create_access_token
from services.audit_logs import ActionType, log_action

URL = "/audit-logs"
START = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def auth(user):
    token = create_access_token(user.user_id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def logs(db_session, sample_fleet_user, sample_user):
    match_id = uuid.uuid4()
    entries = []
    for minutes, user, action, entity_type, entity_id in (
        (0, sample_fleet_user, ActionType.ASSESSMENT_REQUESTED, "match", match_id),
        (1, sample_fleet_user, ActionType.ASSESSMENT_REQUESTED, "match", match_id),
        (2, sample_fleet_user, ActionType.FLEET_UPDATED, "truck", uuid.uuid4()),
        (3, sample_user, ActionType.SHIPMENT_PUBLISHED, "shipment", uuid.uuid4()),
    ):
        entry = log_action(
            db_session, action, user=user, entity_type=entity_type, entity_id=entity_id
        )
        entry.created_at = START + timedelta(minutes=minutes)
        entries.append(entry)
    db_session.commit()
    return {"match_id": match_id, "entries": entries}


def test_company_only_sees_its_own_logs(client, sample_fleet_user, sample_user, logs):
    fleet = client.get(URL, headers=auth(sample_fleet_user)).json()
    shipper = client.get(URL, headers=auth(sample_user)).json()

    assert fleet["total"] == 3
    assert shipper["total"] == 1
    assert {i["company_id"] for i in fleet["items"]} == {
        str(sample_fleet_user.company_id)
    }


def test_filters_pagination_and_order(client, sample_fleet_user, logs):
    headers = auth(sample_fleet_user)

    by_entity = client.get(
        URL, params={"entity_id": str(logs["match_id"])}, headers=headers
    ).json()
    by_action = client.get(
        URL, params={"action_type": "fleet_updated"}, headers=headers
    ).json()
    second_page = client.get(
        URL, params={"limit": 2, "offset": 2}, headers=headers
    ).json()
    everything = client.get(URL, headers=headers).json()

    assert by_entity["total"] == 2
    assert by_action["total"] == 1
    assert len(second_page["items"]) == 1 and second_page["offset"] == 2
    stamps = [i["created_at"] for i in everything["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_bad_query_params_return_422(client, sample_fleet_user):
    headers = auth(sample_fleet_user)
    assert client.get(URL, params={"limit": 500}, headers=headers).status_code == 422
    assert client.get(URL, params={"offset": -1}, headers=headers).status_code == 422
    backwards = {"from": "2026-10-10T00:00:00Z", "to": "2026-10-01T00:00:00Z"}
    assert client.get(URL, params=backwards, headers=headers).status_code == 422


def test_single_entry_respects_company(client, sample_fleet_user, sample_user, logs):
    audit_id = logs["entries"][0].audit_id

    own = client.get(f"{URL}/{audit_id}", headers=auth(sample_fleet_user))
    other = client.get(f"{URL}/{audit_id}", headers=auth(sample_user))

    assert own.status_code == 200
    assert own.json()["action_type"] == "assessment_requested"
    assert other.status_code == 404


def test_requires_login(client):
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer nope"}).status_code == 401
