import pytest

from models import Reservation
from security.tokens import create_access_token
from tests import reservation_data as d

URL = "/reservations"


@pytest.fixture(autouse=True)
def reservation_rows(db_session):
    d.insert_mock_rows(db_session)


def auth(db, user_id) -> dict:
    user = d.get_user(db, user_id)
    token = create_access_token(user.user_id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


def accept(client, db, user_id=d.WILLIAM, match_id=d.MATCH_A_S1):
    return client.post(URL, json={"match_id": str(match_id)}, headers=auth(db, user_id))


def contact(client, db, user_id, shipment_id=d.SHIP_1):
    return client.get(f"/shipments/{shipment_id}/contact", headers=auth(db, user_id))


def test_routes_are_mounted(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/reservations" in paths
    assert "/reservations/{reservation_id}" in paths
    assert "/reservations/{reservation_id}/cancel" in paths
    assert "/shipments/{shipment_id}/contact" in paths


def test_accept_returns_201_with_details(client, db_session):
    res = accept(client, db_session)

    assert res.status_code == 201
    body = res.json()
    assert body["shipment_id"] == str(d.SHIP_1)
    assert body["status"] == "accepted"
    assert body["shipment_status"] == "confirmed"
    assert body["fleet_company_name"] == "Phiri Haulage Ltd"
    assert body["plate_number"] == "MOCK BAZ 1234"


def test_second_company_gets_409(client, db_session):
    accept(client, db_session)

    res = accept(client, db_session, d.MWILA, d.MATCH_B_S1)

    assert res.status_code == 409
    assert res.json()["detail"] == "Load already claimed"
    assert db_session.query(Reservation).count() == 1


def test_shipper_gets_403(client, db_session):
    assert accept(client, db_session, d.KELVIN, d.MATCH_A_S1).status_code == 403


def test_requires_a_valid_login(client):
    body = {"match_id": str(d.MATCH_A_S1)}
    assert client.post(URL, json=body).status_code == 401
    fake = {"Authorization": f"Bearer {d.WILLIAM}"}
    assert client.post(URL, json=body, headers=fake).status_code == 401


def test_inactive_user_is_rejected(client, db_session):
    assert accept(client, db_session, d.INACTIVE).status_code == 401


def test_invalid_body_is_rejected(client, db_session):
    headers = auth(db_session, d.WILLIAM)
    assert (
        client.post(URL, json={"match_id": "nope"}, headers=headers).status_code == 422
    )
    assert client.post(URL, json={}, headers=headers).status_code == 422


def test_list_and_status_filter(client, db_session):
    reservation_id = accept(client, db_session).json()["reservation_id"]
    headers = auth(db_session, d.WILLIAM)

    listed = client.get(URL, headers=headers).json()
    assert [r["reservation_id"] for r in listed] == [reservation_id]
    accepted = client.get(URL, params={"status": "accepted"}, headers=headers)
    assert len(accepted.json()) == 1
    assert (
        client.get(URL, params={"status": "bogus"}, headers=headers).status_code == 422
    )


def test_get_one_reservation(client, db_session):
    reservation_id = accept(client, db_session).json()["reservation_id"]

    for user_id, expected in ((d.WILLIAM, 200), (d.KELVIN, 200), (d.MWILA, 404)):
        res = client.get(f"{URL}/{reservation_id}", headers=auth(db_session, user_id))
        assert res.status_code == expected


def test_cancel(client, db_session):
    reservation_id = accept(client, db_session).json()["reservation_id"]
    headers = auth(db_session, d.WILLIAM)

    res = client.patch(
        f"{URL}/{reservation_id}/cancel",
        json={"reason": "Truck broke down"},
        headers=headers,
    )

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    again = client.patch(f"{URL}/{reservation_id}/cancel", headers=headers)
    assert again.status_code == 409


def test_contact_handoff_over_http(client, db_session):
    before = contact(client, db_session, d.KELVIN)
    assert before.status_code == 200
    assert before.json()["visible"] is False

    accept(client, db_session)

    shipper = contact(client, db_session, d.KELVIN).json()
    winner = contact(client, db_session, d.WILLIAM).json()
    loser = contact(client, db_session, d.MWILA).json()
    assert shipper["business_name"] == "Phiri Haulage Ltd"
    assert winner["business_name"] == "Chipatala Grains Ltd"
    assert loser["visible"] is False


def test_contact_for_unrelated_shipment_is_404(client, db_session):
    assert contact(client, db_session, d.MWILA, d.SHIP_3).status_code == 404
