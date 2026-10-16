import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import models
from database import get_db
from routers.shipments import require_verified_company, router, shipper

PICKUP_TIME = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def shipment_payload(**overrides):
    payload = {
        "origin_address": "123 Origin St",
        "origin_latitude": -15.3875,
        "origin_longitude": 28.3228,
        "destination_address": "456 Dest Ave",
        "destination_latitude": -12.9614,
        "destination_longitude": 28.6366,
        "cargo_type": "Maize",
        "weight_kg": 2500.0,
        "required_body_type": "flatbed",
        "pickup_time": "2026-11-10T09:00:00Z",
        "proposed_amount": 2500.00,
    }
    payload.update(overrides)
    return payload


def shipment_values(company, user, **overrides):
    values = {
        "company_id": company.company_id,
        "user_id": user.user_id,
        "origin_address": "Lusaka",
        "origin_latitude": -15.3875,
        "origin_longitude": 28.3228,
        "destination_address": "Ndola",
        "destination_latitude": -12.9587,
        "destination_longitude": 28.6366,
        "cargo_type": "Grain",
        "weight_kg": 1000.0,
        "required_body_type": models.BodyType.FLATBED,
        "pickup_time": PICKUP_TIME,
        "proposed_amount": 3000.00,
    }
    values.update(overrides)
    return values


def build_test_app(db_session):
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture
def api_client(db_session, sample_company, sample_user):
    app = build_test_app(db_session)
    app.dependency_overrides[shipper] = lambda: sample_user
    app.dependency_overrides[require_verified_company] = lambda: sample_company

    with TestClient(app) as test_client:
        yield test_client


class TestShipment:
    def test_create_shipment_happy_path(self, db_session, sample_company, sample_user):
        shipment = models.Shipment(
            **shipment_values(
                sample_company,
                sample_user,
                origin_address="123 Origin St",
                origin_latitude=40.7128,
                origin_longitude=-74.0060,
                destination_address="456 Dest Ave",
                destination_latitude=34.0522,
                destination_longitude=-118.2437,
                cargo_type="Electronics",
                weight_kg=5000.0,
                special_requirements="Handle with care",
                proposed_amount=15000.00,
            )
        )
        db_session.add(shipment)
        db_session.commit()
        db_session.refresh(shipment)

        assert shipment.shipment_id is not None
        assert isinstance(shipment.shipment_id, uuid.UUID)
        assert shipment.company_id == sample_company.company_id
        assert shipment.user_id == sample_user.user_id
        assert shipment.origin_address == "123 Origin St"
        assert shipment.origin_latitude == pytest.approx(40.7128)
        assert shipment.origin_longitude == pytest.approx(-74.0060)
        assert shipment.destination_address == "456 Dest Ave"
        assert shipment.destination_latitude == pytest.approx(34.0522)
        assert shipment.destination_longitude == pytest.approx(-118.2437)
        assert shipment.cargo_type == "Electronics"
        assert shipment.weight_kg == 5000.0
        assert shipment.required_body_type == models.BodyType.FLATBED
        assert shipment.pickup_time is not None
        assert shipment.special_requirements == "Handle with care"
        assert float(shipment.proposed_amount) == pytest.approx(15000.00)
        assert shipment.status == models.ShipmentStatus.OPEN
        assert shipment.published_at is not None

    def test_shipment_default_status_open(
        self, db_session, sample_company, sample_user
    ):
        shipment = models.Shipment(**shipment_values(sample_company, sample_user))
        db_session.add(shipment)
        db_session.commit()
        db_session.refresh(shipment)

        assert shipment.status == models.ShipmentStatus.OPEN

    @pytest.mark.parametrize(
        "status",
        [
            models.ShipmentStatus.OPEN,
            models.ShipmentStatus.CONFIRMED,
            models.ShipmentStatus.CANCELLED,
            models.ShipmentStatus.EXPIRED,
        ],
    )
    def test_shipment_status_values(
        self, db_session, sample_company, sample_user, status
    ):
        shipment = models.Shipment(
            **shipment_values(sample_company, sample_user, status=status)
        )
        db_session.add(shipment)
        db_session.commit()
        db_session.refresh(shipment)

        assert shipment.status == status

    def test_shipment_optional_special_requirements(
        self, db_session, sample_company, sample_user
    ):
        shipment = models.Shipment(**shipment_values(sample_company, sample_user))
        db_session.add(shipment)
        db_session.commit()
        db_session.refresh(shipment)

        assert shipment.special_requirements is None

    def test_shipment_missing_required_fields(self, db_session):
        shipment = models.Shipment()
        db_session.add(shipment)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    @pytest.mark.parametrize(
        "field",
        [
            "company_id",
            "user_id",
            "origin_address",
            "origin_latitude",
            "origin_longitude",
            "destination_address",
            "destination_latitude",
            "destination_longitude",
            "cargo_type",
            "weight_kg",
            "required_body_type",
            "pickup_time",
            "proposed_amount",
        ],
    )
    def test_shipment_missing_required_field(
        self, db_session, sample_company, sample_user, field
    ):
        values = shipment_values(sample_company, sample_user)
        values.pop(field)
        shipment = models.Shipment(**values)
        db_session.add(shipment)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("origin_latitude", -91),
            ("origin_latitude", 91),
            ("origin_longitude", -181),
            ("origin_longitude", 181),
            ("destination_latitude", -91),
            ("destination_latitude", 91),
            ("destination_longitude", -181),
            ("destination_longitude", 181),
        ],
    )
    def test_shipment_invalid_coordinates(
        self, db_session, sample_company, sample_user, field, value
    ):
        values = shipment_values(sample_company, sample_user)
        values[field] = value
        shipment = models.Shipment(**values)
        db_session.add(shipment)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    @pytest.mark.parametrize("weight", [0, -1, -1000])
    def test_shipment_invalid_weight(
        self, db_session, sample_company, sample_user, weight
    ):
        shipment = models.Shipment(
            **shipment_values(sample_company, sample_user, weight_kg=weight)
        )
        db_session.add(shipment)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    @pytest.mark.parametrize("amount", [0, -1, -1000])
    def test_shipment_invalid_proposed_amount(
        self, db_session, sample_company, sample_user, amount
    ):
        shipment = models.Shipment(
            **shipment_values(sample_company, sample_user, proposed_amount=amount)
        )
        db_session.add(shipment)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    def test_shipment_company_relationship(
        self, db_session, sample_shipment, sample_company
    ):
        assert sample_shipment.company is not None
        assert sample_shipment.company.company_id == sample_company.company_id
        assert sample_shipment in sample_company.shipments

    def test_shipment_user_relationship(self, db_session, sample_shipment, sample_user):
        assert sample_shipment.user is not None
        assert sample_shipment.user.user_id == sample_user.user_id
        assert sample_shipment in sample_user.shipments

    def test_shipment_matches_relationship(
        self, db_session, sample_shipment, sample_truck, sample_fleet_user
    ):
        match = models.ShipmentMatch(
            shipment_id=sample_shipment.shipment_id,
            truck_id=sample_truck.truck_id,
            user_id=sample_fleet_user.user_id,
            distance_km=500.0,
            duration=600,
            fuel_cost=1500.00,
            driver_cost=300.00,
            toll_cost=100.00,
            maintenance_cost=250.00,
            other_cost=50.00,
            estimated_total_cost=2200.00,
            proposed_amount=3000.00,
            estimated_margin=800.00,
        )
        db_session.add(match)
        db_session.commit()
        db_session.refresh(match)

        assert match in sample_shipment.matches
        assert len(sample_shipment.matches) >= 1

    def test_shipment_reservation_relationship(
        self,
        db_session,
        sample_shipment,
        sample_match,
        sample_fleet_company,
        sample_truck,
        sample_fleet_user,
    ):
        reservation = models.Reservation(
            shipment_id=sample_shipment.shipment_id,
            company_id=sample_fleet_company.company_id,
            truck_id=sample_truck.truck_id,
            user_id=sample_fleet_user.user_id,
            match_id=sample_match.match_id,
        )
        db_session.add(reservation)
        db_session.commit()
        db_session.refresh(reservation)

        assert sample_shipment.reservation is not None
        assert sample_shipment.reservation.reservation_id == reservation.reservation_id

    def test_create_shipment_success(self, api_client, sample_company, sample_user):
        response = api_client.post("/shipments", json=shipment_payload())

        assert response.status_code == 201
        data = response.json()
        assert data["cargo_type"] == "Maize"
        assert data["status"] == "open"
        assert data["company_id"] == str(sample_company.company_id)
        assert data["user_id"] == str(sample_user.user_id)
        assert "shipment_id" in data

    def test_create_shipment_invalid_weight(self, api_client):
        response = api_client.post("/shipments", json=shipment_payload(weight_kg=-10.0))

        assert response.status_code == 422

    def test_list_shipments_only_returns_own_company(self, api_client, sample_company):
        api_client.post("/shipments", json=shipment_payload())

        response = api_client.get("/shipments")

        assert response.status_code == 200
        shipments = response.json()
        assert len(shipments) >= 1
        for shipment in shipments:
            assert shipment["company_id"] == str(sample_company.company_id)

    def test_get_shipment_by_id_found(self, api_client):
        create_res = api_client.post(
            "/shipments", json=shipment_payload(cargo_type="Medical Supplies")
        )
        assert create_res.status_code == 201
        shipment_id = create_res.json()["shipment_id"]

        get_res = api_client.get(f"/shipments/{shipment_id}")

        assert get_res.status_code == 200
        assert get_res.json()["shipment_id"] == shipment_id
        assert get_res.json()["cargo_type"] == "Medical Supplies"

    def test_get_shipment_by_id_not_found(self, api_client):
        response = api_client.get(f"/shipments/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_cancel_open_shipment(self, api_client):
        create_res = api_client.post("/shipments", json=shipment_payload())
        assert create_res.status_code == 201
        shipment_id = create_res.json()["shipment_id"]

        cancel_res = api_client.post(f"/shipments/{shipment_id}/cancel")

        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"

    def test_cannot_cancel_shipment_twice(self, api_client):
        create_res = api_client.post("/shipments", json=shipment_payload())
        shipment_id = create_res.json()["shipment_id"]
        api_client.post(f"/shipments/{shipment_id}/cancel")

        again_res = api_client.post(f"/shipments/{shipment_id}/cancel")

        assert again_res.status_code == 409

    def test_shipments_locked_until_login_is_available(self, db_session):
        app = build_test_app(db_session)

        with TestClient(app) as test_client:
            response = test_client.get("/shipments")

        assert response.status_code == 401
