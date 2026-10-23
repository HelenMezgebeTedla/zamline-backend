import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from database import get_db
from fleet_helpers import (
    create_fleet_manager,
    create_shipment,
    create_shipper,
    create_test_engine,
    create_test_sessionmaker,
    create_truck,
    stub_assessment_services,
)
from routers.shipment_matches import router as shipment_matches_router
from security.tokens import create_access_token
from services.routing import (
    GeocodedPlace,
    GeocodingUnavailableError,
    RouteSummary,
    RouteUnavailableError,
)


@pytest.fixture
def api():
    engine = create_test_engine()
    TestSession = create_test_sessionmaker(engine)

    app = FastAPI()
    app.include_router(shipment_matches_router)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    setup_db = TestSession()

    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            db=setup_db,
        )

    setup_db.close()
    engine.dispose()


@pytest.fixture
def market(api):
    db = api.db

    fleet_a, manager_a = create_fleet_manager(
        db,
        "FA",
    )
    create_truck(
        db,
        fleet_a,
        "FA",
    )

    fleet_b, manager_b = create_fleet_manager(
        db,
        "FB",
    )
    create_truck(
        db,
        fleet_b,
        "FB",
    )

    shipper, shipper_user = create_shipper(
        db,
        "SH",
    )

    create_shipment(
        db,
        shipper,
        shipper_user,
        "SH",
        special_requirements="Handle with care",
    )

    return SimpleNamespace(
        fleet_a=fleet_a,
        manager_a=manager_a,
        fleet_b=fleet_b,
        manager_b=manager_b,
        shipper=shipper,
        shipper_user=shipper_user,
    )


def auth_headers(user):
    token = create_access_token(
        user.user_id,
        user.role.value,
    )

    return {
        "Authorization": f"Bearer {token}",
    }


def generate(client, user, params=None):
    return client.post(
        "/shipment-matches/generate",
        headers=auth_headers(user),
        params=params or {},
    )


def get_opportunities(client, user):
    return client.get(
        "/shipment-matches/opportunities",
        headers=auth_headers(user),
    )


def post_match_action(
    client,
    match_id,
    action,
    user,
    params=None,
):
    return client.post(
        f"/shipment-matches/{match_id}/{action}",
        headers=auth_headers(user),
        params=params or {},
    )


def get_detail(
    client,
    match_id,
    user,
    params=None,
):
    return client.get(
        f"/shipment-matches/{match_id}",
        headers=auth_headers(user),
        params=params or {},
    )


def test_full_fleet_manager_flow(
    api,
    market,
    monkeypatch,
):
    stub_assessment_services(monkeypatch)

    generated = generate(
        api.client,
        market.manager_a,
    )

    assert generated.status_code == 200

    match_id = generated.json()[0]["match_id"]

    opportunities = get_opportunities(
        api.client,
        market.manager_a,
    )

    assert opportunities.status_code == 200
    assert [item["match_id"] for item in opportunities.json()] == [match_id]

    detail = get_detail(
        api.client,
        match_id,
        market.manager_a,
    )

    assert detail.status_code == 200
    assert detail.json()["shipment"]["special_requirements"] == "Handle with care"
    assert detail.json()["assessment"] is None

    started = post_match_action(
        api.client,
        match_id,
        "assessment",
        market.manager_a,
    )

    assert started.status_code == 200
    assert started.json()["route"] == {
        "distance_km": 320.0,
        "duration_minutes": 270,
    }
    assert started.json()["assessment_status"] == "running"
    assert started.json()["operating_cost_total"] == "4090.00"
    assert started.json()["assessment"] is None
    assert started.json()["estimated_total_cost"] is None
    assert started.json()["estimated_margin"] is None
    assert started.json()["outcome"] is None

    assessed_response = get_detail(
        api.client,
        match_id,
        market.manager_a,
    )

    assert assessed_response.status_code == 200

    assessed = assessed_response.json()

    assert assessed["assessment_status"] == "completed"
    assert assessed["estimated_total_cost"] == "4540.00"
    assert assessed["estimated_margin"] == "13960.00"
    assert assessed["outcome"] == "profit"
    assert assessed["manager_decision"] == "pending"
    assert assessed["assessment"]["summary"]

    accepted = post_match_action(
        api.client,
        match_id,
        "accept",
        market.manager_a,
    )

    assert accepted.status_code == 200
    assert accepted.json()["manager_decision"] == "accepted"


def test_skip_records_declined_decision(
    api,
    market,
):
    match_id = generate(
        api.client,
        market.manager_a,
    ).json()[0]["match_id"]

    skipped = post_match_action(
        api.client,
        match_id,
        "skip",
        market.manager_a,
    )

    assert skipped.status_code == 200
    assert skipped.json()["manager_decision"] == "declined"

    assert (
        get_detail(
            api.client,
            match_id,
            market.manager_a,
        ).status_code
        == 409
    )


def test_unavailable_route_returns_503_and_saves_nothing(
    api,
    market,
    monkeypatch,
):
    def failing_route(shipment):
        raise RouteUnavailableError("Route could not be calculated")

    monkeypatch.setattr(
        "services.shipment_matches.get_route_summary",
        failing_route,
    )

    match_id = generate(
        api.client,
        market.manager_a,
    ).json()[0]["match_id"]

    response = post_match_action(
        api.client,
        match_id,
        "assessment",
        market.manager_a,
    )

    assert response.status_code == 503

    api.db.expire_all()

    match = api.db.get(
        models.ShipmentMatch,
        uuid.UUID(match_id),
    )

    assert match.distance_km is None


def test_missing_bearer_token_returns_401(
    api,
):
    response = api.client.get("/shipment-matches/opportunities")

    assert response.status_code == 401


def test_actor_user_id_cannot_replace_authentication(
    api,
    market,
):
    response = api.client.post(
        "/shipment-matches/generate",
        params={"actor_user_id": str(market.manager_a.user_id)},
    )

    assert response.status_code == 401


def test_invalid_bearer_token_returns_401(
    api,
):
    response = api.client.get(
        "/shipment-matches/opportunities",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401


def test_shipper_cannot_use_fleet_endpoints(
    api,
    market,
):
    response = generate(
        api.client,
        market.shipper_user,
    )

    assert response.status_code == 403


def test_unverified_fleet_company_returns_403(
    api,
):
    fleet, manager = create_fleet_manager(
        api.db,
        "FU",
        verification_status=(models.VerificationStatus.PENDING),
    )

    response = generate(
        api.client,
        manager,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "action",
    [
        "assessment",
        "accept",
        "skip",
    ],
)
def test_other_company_match_actions_return_403(
    api,
    market,
    action,
):
    match_a = generate(
        api.client,
        market.manager_a,
    ).json()[0]["match_id"]

    response = post_match_action(
        api.client,
        match_a,
        action,
        market.manager_b,
    )

    assert response.status_code == 403

    detail = get_detail(
        api.client,
        match_a,
        market.manager_b,
    )

    assert detail.status_code == 403


def test_query_parameter_cannot_spoof_another_manager(
    api,
    market,
):
    match_a = generate(
        api.client,
        market.manager_a,
    ).json()[0]["match_id"]

    own_response = get_detail(
        api.client,
        match_a,
        market.manager_a,
        params={"actor_user_id": str(market.manager_b.user_id)},
    )

    assert own_response.status_code == 200

    other_response = get_detail(
        api.client,
        match_a,
        market.manager_b,
        params={"actor_user_id": str(market.manager_a.user_id)},
    )

    assert other_response.status_code == 403


def test_missing_match_returns_404(
    api,
    market,
):
    response = get_detail(
        api.client,
        uuid.uuid4(),
        market.manager_a,
    )

    assert response.status_code == 404


def test_responses_do_not_leak_private_data(
    api,
    market,
    monkeypatch,
):
    stub_assessment_services(monkeypatch)

    match_a = generate(
        api.client,
        market.manager_a,
    ).json()[0]["match_id"]

    assessed = post_match_action(
        api.client,
        match_a,
        "assessment",
        market.manager_a,
    )

    detail = get_detail(
        api.client,
        match_a,
        market.manager_a,
    )

    accepted = post_match_action(
        api.client,
        match_a,
        "accept",
        market.manager_a,
    )

    for response in (
        assessed,
        detail,
        accepted,
    ):
        for hidden in (
            "fuel_price_per_litre",
            "driver_daily_allowance",
            "toll_assumption",
            "maintenance_per_km",
            "password_hash",
            "certificate_file_url",
            "company_id",
            "company_email",
            "phone_number",
            "example.test/files",
            "api_key",
            "gemini_api_key",
            "fileSearchStores/",
        ):
            assert hidden not in response.text


def test_geocode_returns_places_for_fleet_manager(
    api,
    market,
    monkeypatch,
):
    def fake_geocode(text, size):
        return [
            GeocodedPlace(
                label="Lusaka, Zambia",
                latitude=-15.4167,
                longitude=28.2833,
            )
        ]

    monkeypatch.setattr(
        "services.shipment_matches.geocode_address",
        fake_geocode,
    )

    response = api.client.get(
        "/shipment-matches/geocode",
        headers=auth_headers(market.manager_a),
        params={
            "text": "Lusaka",
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "label": "Lusaka, Zambia",
            "latitude": -15.4167,
            "longitude": 28.2833,
        }
    ]


def test_route_estimate_returns_distance_and_duration(
    api,
    market,
    monkeypatch,
):
    monkeypatch.setattr(
        ("services.shipment_matches.get_route_between_coordinates"),
        lambda *coordinates: RouteSummary(
            distance_km=320.0,
            duration_minutes=270,
        ),
    )

    response = api.client.get(
        "/shipment-matches/route",
        headers=auth_headers(market.manager_a),
        params={
            "origin_latitude": -15.4167,
            "origin_longitude": 28.2833,
            "destination_latitude": -12.8,
            "destination_longitude": 28.2,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "distance_km": 320.0,
        "duration_minutes": 270,
    }


def test_unavailable_geocoding_returns_503(
    api,
    market,
    monkeypatch,
):
    def failing_geocode(text, size):
        raise GeocodingUnavailableError("Address could not be geocoded")

    monkeypatch.setattr(
        "services.shipment_matches.geocode_address",
        failing_geocode,
    )

    response = api.client.get(
        "/shipment-matches/geocode",
        headers=auth_headers(market.manager_a),
        params={
            "text": "Lusaka",
        },
    )

    assert response.status_code == 503


def test_shipper_cannot_use_geocode_endpoint(
    api,
    market,
):
    response = api.client.get(
        "/shipment-matches/geocode",
        headers=auth_headers(market.shipper_user),
        params={
            "text": "Lusaka",
        },
    )

    assert response.status_code == 403
