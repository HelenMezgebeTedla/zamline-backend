import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

import models
from database import get_db
from dependency import require_verified_company
from main import app
from repositories import trucks as truck_repo
from routers import trucks as truck_router
from schemas.trucks import (
    TruckAvailabilityUpdate,
    TruckCreate,
    TruckRetireRequest,
    TruckUpdate,
    normalize_plate,
)
from services import trucks as truck_service


MOCK_PICKUP = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def make_company(db, name, reg, company_type=models.CompanyType.FLEET, **extra):
    """A company row as Helen's registration + PACRA flow would leave it."""
    values = {
        "company_type": company_type,
        "business_name": name,
        "registration_number": reg,
        "company_email": f"ops@{reg.lower()}-mock.com",
        "phone_number": "+260970000000",
        "verification_status": models.VerificationStatus.VERIFIED,
        "verified_at": datetime.now(timezone.utc),
    }
    values.update(extra)
    company = models.Company(**values)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def make_user(db, company, email, role=models.UserRole.FLEET_MANAGER, **extra):
    """A user who has registered and verified their email OTP."""
    values = {
        "company_id": company.company_id,
        "first_name": email.split("@")[0].split(".")[0].title(),
        "last_name": "Mock",
        "email": email,
        "password_hash": "mock-hash-not-a-real-password",
        "role": role,
        "is_active": True,
    }
    values.update(extra)
    user = models.User(**values)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_truck(db, company, plate, **extra):
    values = {
        "company_id": company.company_id,
        "plate_number": plate,
        "truck_type": "Rigid",
        "body_type": models.BodyType.FLATBED,
        "capacity_kg": 20000.0,
        "fuel_consumption_l_per_100km": 30.0,
        "maintenance_per_km": Decimal("2.00"),
    }
    values.update(extra)
    truck = models.Truck(**values)
    db.add(truck)
    db.commit()
    db.refresh(truck)
    return truck


def truck_payload(**overrides):
    """Valid body for POST /trucks / TruckCreate."""
    body = {
        "plate_number": "BAD 4321",
        "truck_type": "Interlink",
        "body_type": "flatbed",
        "capacity_kg": 30000,
        "fuel_consumption_l_per_100km": 33.5,
        "maintenance_per_km": "2.40",
        "current_location": "Lusaka",
    }
    body.update(overrides)
    return body


def audit_events(db, action_type=None, entity_id=None):
    query = db.query(models.AuditLog)
    if action_type:
        query = query.filter(models.AuditLog.action_type == action_type)
    if entity_id:
        query = query.filter(models.AuditLog.entity_id == entity_id)
    return query.order_by(models.AuditLog.created_at).all()


@pytest.fixture
def fleet_company(db_session):
    """Verified fleet company with private cost settings filled in."""
    return make_company(
        db_session,
        "Mwape Haulage Ltd",
        "PACRA-T0001",
        fuel_price_per_litre=Decimal("27.50"),
        driver_daily_allowance=Decimal("450.00"),
    )


@pytest.fixture
def fleet_manager(db_session, fleet_company):
    return make_user(db_session, fleet_company, "mwape.banda@mwape-mock.com")


@pytest.fixture
def rival_company(db_session):
    return make_company(db_session, "Kafue Transporters", "PACRA-T0002")


@pytest.fixture
def rival_manager(db_session, rival_company):
    return make_user(db_session, rival_company, "chanda@kafue-mock.com")


@pytest.fixture
def unverified_company(db_session):
    return make_company(
        db_session,
        "Pending Logistics",
        "PACRA-T0003",
        verification_status=models.VerificationStatus.PENDING,
        verified_at=None,
    )


@pytest.fixture
def unverified_manager(db_session, unverified_company):
    return make_user(db_session, unverified_company, "bwalya@pending-mock.com")


@pytest.fixture
def shipper_company(db_session):
    return make_company(
        db_session,
        "Copperbelt Metals Ltd",
        "PACRA-T0004",
        company_type=models.CompanyType.SHIPPER,
    )


@pytest.fixture
def shipper_user(db_session, shipper_company):
    return make_user(
        db_session,
        shipper_company,
        "mwaka@copperbelt-mock.com",
        role=models.UserRole.SHIPPER,
    )


@pytest.fixture
def audit_history(db_session, fleet_company, fleet_manager):
    """Events Helen's feature writes before a fleet manager ever adds a truck."""
    for action in ("user_registered", "email_verified", "login_success"):
        db_session.add(
            models.AuditLog(
                user_id=fleet_manager.user_id,
                company_id=fleet_company.company_id,
                action_type=action,
                entity_type="user",
                entity_id=fleet_manager.user_id,
            )
        )
    db_session.commit()
    return audit_events(db_session)


@pytest.fixture
def fleet_trucks(db_session, fleet_company, rival_company):
    """A small fleet in every state, plus one truck from another company."""
    return {
        "flatbed": make_truck(
            db_session, fleet_company, "BAA 1001", current_location="Lusaka"
        ),
        "reefer": make_truck(
            db_session,
            fleet_company,
            "BAA 1002",
            body_type=models.BodyType.REFRIGERATED,
            capacity_kg=12000.0,
        ),
        "workshop": make_truck(
            db_session,
            fleet_company,
            "BAA 1003",
            body_type=models.BodyType.BOX,
            availability_status=models.AvailabilityStatus.UNAVAILABLE,
        ),
        "retired": make_truck(
            db_session,
            fleet_company,
            "BAA 1005",
            body_type=models.BodyType.TIPPER,
            availability_status=models.AvailabilityStatus.RETIRED,
        ),
        "rival": make_truck(db_session, rival_company, "BCC 2001"),
    }


@pytest.fixture
def allocated_truck(
    db_session, fleet_company, fleet_manager, shipper_company, shipper_user
):
    """A truck tied to a confirmed shipment (stands in for Sandra's
    shipments and Shamy's acceptance flow)."""
    truck = make_truck(
        db_session,
        fleet_company,
        "BAA 1004",
        body_type=models.BodyType.CONTAINER,
        capacity_kg=28000.0,
        availability_status=models.AvailabilityStatus.UNAVAILABLE,
    )
    shipment = models.Shipment(
        company_id=shipper_company.company_id,
        user_id=shipper_user.user_id,
        origin_address="Kitwe, Zambia",
        origin_latitude=-12.8024,
        origin_longitude=28.2132,
        destination_address="Lusaka, Zambia",
        destination_latitude=-15.4167,
        destination_longitude=28.2833,
        cargo_type="Copper cathodes",
        weight_kg=25000.0,
        required_body_type=models.BodyType.CONTAINER,
        pickup_time=MOCK_PICKUP,
        proposed_amount=Decimal("18500.00"),
        status=models.ShipmentStatus.CONFIRMED,
    )
    db_session.add(shipment)
    db_session.flush()
    match = models.ShipmentMatch(
        shipment_id=shipment.shipment_id,
        truck_id=truck.truck_id,
        user_id=fleet_manager.user_id,
        manager_decision=models.ManagerDecision.ACCEPTED,
    )
    db_session.add(match)
    db_session.flush()
    reservation = models.Reservation(
        shipment_id=shipment.shipment_id,
        company_id=fleet_company.company_id,
        truck_id=truck.truck_id,
        user_id=fleet_manager.user_id,
        match_id=match.match_id,
    )
    db_session.add(reservation)
    db_session.commit()
    db_session.refresh(truck)
    return {"truck": truck, "shipment": shipment, "reservation": reservation}


class TestMockData:
    """The mock data itself must be valid, or every other test is misleading."""

    def test_fleet_manager_belongs_to_verified_fleet_company(
        self, fleet_manager, fleet_company
    ):
        assert fleet_manager.company_id == fleet_company.company_id
        assert fleet_manager.role == models.UserRole.FLEET_MANAGER
        assert fleet_manager.is_active is True
        assert fleet_company.company_type == models.CompanyType.FLEET
        assert fleet_company.verification_status == models.VerificationStatus.VERIFIED

    def test_unverified_company_is_pending(self, unverified_company):
        assert (
            unverified_company.verification_status == models.VerificationStatus.PENDING
        )

    def test_audit_history_is_linked_to_user_and_company(
        self, audit_history, fleet_manager, fleet_company
    ):
        assert [e.action_type for e in audit_history] == [
            "user_registered",
            "email_verified",
            "login_success",
        ]
        for event in audit_history:
            assert event.user_id == fleet_manager.user_id
            assert event.company_id == fleet_company.company_id

    def test_allocated_truck_has_confirmed_reservation(self, allocated_truck):
        reservation = allocated_truck["reservation"]
        assert reservation.status == models.ReservationStatus.ACCEPTED
        assert reservation.shipment.status == models.ShipmentStatus.CONFIRMED
        assert reservation.truck_id == allocated_truck["truck"].truck_id


class TestTruck:
    def test_create_truck_happy_path(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        db_session.commit()
        db_session.refresh(truck)

        assert truck.truck_id is not None
        assert isinstance(truck.truck_id, uuid.UUID)
        assert truck.company_id == sample_fleet_company.company_id
        assert truck.plate_number == "ABC-1234"
        assert truck.truck_type == "Heavy Duty"
        assert truck.body_type == models.BodyType.FLATBED
        assert truck.capacity_kg == 10000.0
        assert truck.fuel_consumption_l_per_100km == 30.0
        assert truck.maintenance_per_km == Decimal("2.50")
        assert truck.availability_status == models.AvailabilityStatus.AVAILABLE
        assert truck.current_location is None
        assert truck.available_from is None
        assert truck.created_at is not None
        assert truck.updated_at is not None

    def test_create_truck_all_body_types(self, db_session, sample_fleet_company):
        for body_type in models.BodyType:
            truck = models.Truck(
                company_id=sample_fleet_company.company_id,
                plate_number=f"TEST-{body_type.value.upper()[:4]}",
                truck_type="Test Truck",
                body_type=body_type,
                capacity_kg=10000.0,
                fuel_consumption_l_per_100km=30.0,
                maintenance_per_km=Decimal("2.50"),
            )
            db_session.add(truck)
            db_session.commit()
            db_session.refresh(truck)

            assert truck.body_type == body_type

    def test_truck_default_availability_status_available(
        self, db_session, sample_fleet_company
    ):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        db_session.commit()
        db_session.refresh(truck)

        assert truck.availability_status == models.AvailabilityStatus.AVAILABLE

    def test_truck_explicit_availability_status_unavailable(
        self, db_session, sample_fleet_company
    ):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
            availability_status=models.AvailabilityStatus.UNAVAILABLE,
        )
        db_session.add(truck)
        db_session.commit()
        db_session.refresh(truck)

        assert truck.availability_status == models.AvailabilityStatus.UNAVAILABLE

    def test_truck_retired_status_can_be_stored(self, db_session, fleet_company):
        truck = make_truck(
            db_session,
            fleet_company,
            "RET 0001",
            availability_status=models.AvailabilityStatus.RETIRED,
        )
        assert truck.availability_status == models.AvailabilityStatus.RETIRED

    def test_availability_status_values(self):
        assert {status.value for status in models.AvailabilityStatus} == {
            "available",
            "unavailable",
            "retired",
        }

    def test_truck_unique_plate_number(self, db_session, sample_fleet_company):
        truck1 = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck1)
        db_session.commit()

        truck2 = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Light Duty",
            body_type=models.BodyType.BOX,
            capacity_kg=5000.0,
            fuel_consumption_l_per_100km=20.0,
            maintenance_per_km=Decimal("1.50"),
        )
        db_session.add(truck2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_plate_is_unique_across_companies(
        self, db_session, fleet_company, rival_company
    ):
        make_truck(db_session, fleet_company, "SAME 001")
        db_session.add(
            models.Truck(
                company_id=rival_company.company_id,
                plate_number="SAME 001",
                truck_type="Rigid",
                body_type=models.BodyType.BOX,
                capacity_kg=5000.0,
                fuel_consumption_l_per_100km=20.0,
                maintenance_per_km=Decimal("1.50"),
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_missing_required_fields(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_missing_company_id(self, db_session):
        truck = models.Truck(
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_unknown_company_id_is_rejected(self, db_session):
        db_session.add(
            models.Truck(
                company_id=uuid.uuid4(),
                plate_number="GHOST 01",
                truck_type="Rigid",
                body_type=models.BodyType.BOX,
                capacity_kg=5000.0,
                fuel_consumption_l_per_100km=20.0,
                maintenance_per_km=Decimal("1.50"),
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_missing_plate_number(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_missing_body_type(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_missing_truck_type(self, db_session, fleet_company):
        db_session.add(
            models.Truck(
                company_id=fleet_company.company_id,
                plate_number="NOTYPE 1",
                body_type=models.BodyType.BOX,
                capacity_kg=5000.0,
                fuel_consumption_l_per_100km=20.0,
                maintenance_per_km=Decimal("1.50"),
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_capacity_positive_constraint(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=-1000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_capacity_zero_constraint(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_fuel_consumption_positive_constraint(
        self, db_session, sample_fleet_company
    ):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=-5.0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_fuel_consumption_zero_constraint(
        self, db_session, sample_fleet_company
    ):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=0,
            maintenance_per_km=Decimal("2.50"),
        )
        db_session.add(truck)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_truck_optional_fields(self, db_session, sample_fleet_company):
        truck = models.Truck(
            company_id=sample_fleet_company.company_id,
            plate_number="ABC-1234",
            truck_type="Heavy Duty",
            body_type=models.BodyType.FLATBED,
            capacity_kg=10000.0,
            fuel_consumption_l_per_100km=30.0,
            maintenance_per_km=Decimal("2.50"),
            current_location="Warehouse A",
            available_from=datetime(2026, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
        )
        db_session.add(truck)
        db_session.commit()
        db_session.refresh(truck)

        assert truck.current_location == "Warehouse A"
        assert truck.available_from is not None

    def test_truck_company_relationship(
        self, db_session, sample_truck, sample_fleet_company
    ):
        assert sample_truck.company is not None
        assert sample_truck.company.company_id == sample_fleet_company.company_id
        assert sample_truck.company.business_name == sample_fleet_company.business_name

    def test_truck_company_back_populates(
        self, db_session, sample_truck, sample_fleet_company
    ):
        assert sample_truck in sample_fleet_company.trucks

    def test_truck_shipment_matches_relationship(
        self, db_session, sample_truck, sample_shipment, sample_fleet_user
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

        assert match in sample_truck.shipment_matches
        assert len(sample_truck.shipment_matches) == 1

    def test_truck_reservations_relationship(
        self,
        db_session,
        sample_truck,
        sample_shipment,
        sample_match,
        sample_fleet_company,
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

        assert reservation in sample_truck.reservations
        assert len(sample_truck.reservations) == 1

    def test_truck_cascade_delete_on_company_delete(
        self, db_session, sample_fleet_company, sample_truck
    ):
        truck_id = sample_truck.truck_id
        db_session.delete(sample_fleet_company)
        db_session.commit()

        deleted_truck = (
            db_session.query(models.Truck)
            .filter(models.Truck.truck_id == truck_id)
            .first()
        )
        assert deleted_truck is None


class TestTruckSchemas:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("baa 1001", "BAA 1001"),
            ("  BAA   1001  ", "BAA 1001"),
            ("abc-1234", "ABC-1234"),
            ("zm\t77", "ZM 77"),
        ],
    )
    def test_plate_is_normalised(self, raw, expected):
        assert normalize_plate(raw) == expected
        assert TruckCreate(**truck_payload(plate_number=raw)).plate_number == expected

    def test_valid_create_payload(self):
        data = TruckCreate(**truck_payload())
        assert data.body_type == models.BodyType.FLATBED
        assert data.maintenance_per_km == Decimal("2.40")
        assert data.available_from is None

    def test_truck_type_is_trimmed(self):
        assert TruckCreate(**truck_payload(truck_type="  Tipper ")).truck_type == (
            "Tipper"
        )

    @pytest.mark.parametrize(
        "field, value",
        [
            ("plate_number", ""),
            ("plate_number", "   "),
            ("plate_number", "X" * 21),
            ("truck_type", "A"),
            ("body_type", "spaceship"),
            ("capacity_kg", 0),
            ("capacity_kg", -1),
            ("fuel_consumption_l_per_100km", 0),
            ("maintenance_per_km", "0"),
            ("current_location", "L" * 51),
        ],
    )
    def test_invalid_create_values(self, field, value):
        with pytest.raises(ValidationError):
            TruckCreate(**truck_payload(**{field: value}))

    @pytest.mark.parametrize(
        "missing",
        [
            "plate_number",
            "truck_type",
            "body_type",
            "capacity_kg",
            "fuel_consumption_l_per_100km",
            "maintenance_per_km",
        ],
    )
    def test_required_create_fields(self, missing):
        body = truck_payload()
        del body[missing]
        with pytest.raises(ValidationError):
            TruckCreate(**body)

    def test_update_only_tracks_fields_sent(self):
        data = TruckUpdate(capacity_kg=15000)
        assert data.model_dump(exclude_unset=True) == {"capacity_kg": 15000}

    @pytest.mark.parametrize(
        "body",
        [
            {"plate_number": "NEW 1"},
            {"availability_status": "available"},
            {"company_id": str(uuid.uuid4())},
        ],
    )
    def test_update_rejects_fields_it_does_not_own(self, body):
        with pytest.raises(ValidationError):
            TruckUpdate(**body)

    @pytest.mark.parametrize(
        "field",
        ["truck_type", "body_type", "capacity_kg", "maintenance_per_km"],
    )
    def test_update_cannot_blank_required_fields(self, field):
        with pytest.raises(ValidationError):
            TruckUpdate(**{field: None})

    def test_update_can_clear_location(self):
        assert TruckUpdate(current_location=None).model_dump(exclude_unset=True) == {
            "current_location": None
        }

    def test_availability_accepts_available_and_unavailable(self):
        for value in ("available", "unavailable"):
            assert TruckAvailabilityUpdate(availability_status=value)

    def test_availability_rejects_retired(self):
        with pytest.raises(ValidationError, match="retire"):
            TruckAvailabilityUpdate(availability_status="retired")

    def test_retire_reason_is_optional_and_limited(self):
        assert TruckRetireRequest().reason is None
        with pytest.raises(ValidationError):
            TruckRetireRequest(reason="x" * 256)


class TestTruckRepository:
    def test_get_truck_by_plate(self, db_session, fleet_trucks):
        found = truck_repo.get_truck_by_plate(db_session, "BAA 1001")
        assert found.truck_id == fleet_trucks["flatbed"].truck_id
        assert truck_repo.get_truck_by_plate(db_session, "NOPE 000") is None

    def test_get_company_truck_is_scoped(
        self, db_session, fleet_trucks, fleet_company, rival_company
    ):
        truck_id = fleet_trucks["flatbed"].truck_id
        assert truck_repo.get_company_truck(
            db_session, fleet_company.company_id, truck_id
        )
        assert (
            truck_repo.get_company_truck(db_session, rival_company.company_id, truck_id)
            is None
        )

    def test_search_hides_retired_by_default(
        self, db_session, fleet_trucks, fleet_company
    ):
        plates = [
            t.plate_number
            for t in truck_repo.search_company_trucks(
                db_session, fleet_company.company_id
            )
        ]
        assert sorted(plates) == ["BAA 1001", "BAA 1002", "BAA 1003"]

    def test_search_can_include_retired(self, db_session, fleet_trucks, fleet_company):
        trucks = truck_repo.search_company_trucks(
            db_session, fleet_company.company_id, include_retired=True
        )
        assert len(trucks) == 4

    def test_search_by_status_and_body(self, db_session, fleet_trucks, fleet_company):
        company_id = fleet_company.company_id
        retired = truck_repo.search_company_trucks(
            db_session,
            company_id,
            availability_status=models.AvailabilityStatus.RETIRED,
        )
        assert [t.plate_number for t in retired] == ["BAA 1005"]

        reefers = truck_repo.search_company_trucks(
            db_session, company_id, body_type=models.BodyType.REFRIGERATED
        )
        assert [t.plate_number for t in reefers] == ["BAA 1002"]

    def test_list_available_only_returns_available(
        self, db_session, fleet_trucks, fleet_company
    ):
        plates = {
            t.plate_number
            for t in truck_repo.list_available_company_trucks(
                db_session, fleet_company.company_id
            )
        }
        assert plates == {"BAA 1001", "BAA 1002"}

    def test_active_reservation_found(self, db_session, allocated_truck):
        reservation = truck_repo.get_active_reservation_for_truck(
            db_session, allocated_truck["truck"].truck_id
        )
        assert (
            reservation.reservation_id == allocated_truck["reservation"].reservation_id
        )

    def test_no_reservation_for_free_truck(self, db_session, fleet_trucks):
        assert (
            truck_repo.get_active_reservation_for_truck(
                db_session, fleet_trucks["flatbed"].truck_id
            )
            is None
        )

    @pytest.mark.parametrize(
        "change",
        ["cancel_reservation", "cancel_shipment", "expire_shipment"],
    )
    def test_inactive_reservation_is_ignored(self, db_session, allocated_truck, change):
        if change == "cancel_reservation":
            allocated_truck["reservation"].status = models.ReservationStatus.CANCELLED
        elif change == "cancel_shipment":
            allocated_truck["shipment"].status = models.ShipmentStatus.CANCELLED
        else:
            allocated_truck["shipment"].status = models.ShipmentStatus.EXPIRED
        db_session.commit()

        assert (
            truck_repo.get_active_reservation_for_truck(
                db_session, allocated_truck["truck"].truck_id
            )
            is None
        )


class TestCreateTruckService:
    def test_creates_truck_for_managers_company(
        self, db_session, fleet_company, fleet_manager
    ):
        truck = truck_service.create_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            TruckCreate(**truck_payload(plate_number="bad 4321")),
        )

        assert truck.company_id == fleet_company.company_id
        assert truck.plate_number == "BAD 4321"
        assert truck.availability_status == models.AvailabilityStatus.AVAILABLE
        assert truck in fleet_company.trucks

    def test_writes_audit_log_linked_to_user_and_company(
        self, db_session, fleet_company, fleet_manager, audit_history
    ):
        truck = truck_service.create_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            TruckCreate(**truck_payload()),
        )

        events = audit_events(db_session)
        assert len(events) == len(audit_history) + 1
        created = audit_events(db_session, "truck_created")[0]
        assert created.user_id == fleet_manager.user_id
        assert created.company_id == fleet_company.company_id
        assert created.entity_type == "truck"
        assert created.entity_id == truck.truck_id
        assert created.details == {"plate_number": "BAD 4321"}

    def test_duplicate_plate_returns_409_and_writes_nothing(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.create_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                TruckCreate(**truck_payload(plate_number=" baa  1001")),
            )

        assert error.value.status_code == 409
        assert audit_events(db_session, "truck_created") == []

    def test_plate_of_retired_or_rival_truck_cannot_be_reused(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        for plate in ("BAA 1005", "BCC 2001"):
            with pytest.raises(HTTPException) as error:
                truck_service.create_truck(
                    db_session,
                    fleet_company.company_id,
                    fleet_manager.user_id,
                    TruckCreate(**truck_payload(plate_number=plate)),
                )
            assert error.value.status_code == 409

    def test_database_race_on_plate_is_turned_into_409(
        self, db_session, fleet_company, fleet_manager, monkeypatch
    ):
        # Simulates two requests registering the same plate at the same time:
        # the pre-check passes, then the unique constraint fires.
        def raise_integrity(*args, **kwargs):
            raise IntegrityError("insert", {}, Exception("duplicate"))

        monkeypatch.setattr(truck_service, "create_truck_record", raise_integrity)
        with pytest.raises(HTTPException) as error:
            truck_service.create_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                TruckCreate(**truck_payload()),
            )
        assert error.value.status_code == 409


class TestReadTruckService:
    def test_get_truck(self, db_session, fleet_company, fleet_trucks):
        truck = truck_service.get_truck(
            db_session, fleet_company.company_id, fleet_trucks["reefer"].truck_id
        )
        assert truck.plate_number == "BAA 1002"

    def test_other_company_gets_404(self, db_session, rival_company, fleet_trucks):
        with pytest.raises(HTTPException) as error:
            truck_service.get_truck(
                db_session, rival_company.company_id, fleet_trucks["reefer"].truck_id
            )
        assert error.value.status_code == 404

    def test_unknown_truck_gets_404(self, db_session, fleet_company):
        with pytest.raises(HTTPException) as error:
            truck_service.get_truck(db_session, fleet_company.company_id, uuid.uuid4())
        assert error.value.status_code == 404

    def test_list_trucks_never_includes_rival_trucks(
        self, db_session, fleet_company, fleet_trucks
    ):
        trucks = truck_service.list_trucks(
            db_session, fleet_company.company_id, include_retired=True
        )
        assert fleet_trucks["rival"] not in trucks
        assert len(trucks) == 4

    def test_company_with_no_trucks_gets_empty_list(
        self, db_session, unverified_company
    ):
        assert (
            truck_service.list_trucks(db_session, unverified_company.company_id) == []
        )


class TestUpdateTruckService:
    def test_updates_fields_and_audits_which_changed(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck = truck_service.update_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["flatbed"].truck_id,
            TruckUpdate(capacity_kg=32000, current_location="Kabwe"),
        )

        assert truck.capacity_kg == 32000
        assert truck.current_location == "Kabwe"
        event = audit_events(db_session, "truck_updated")[0]
        assert event.details == {"updated_fields": ["capacity_kg", "current_location"]}
        assert event.user_id == fleet_manager.user_id

    def test_fields_not_sent_are_unchanged(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck = truck_service.update_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["flatbed"].truck_id,
            TruckUpdate(truck_type="Interlink"),
        )
        assert truck.capacity_kg == 20000.0
        assert truck.body_type == models.BodyType.FLATBED

    def test_empty_update_is_400(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                fleet_trucks["flatbed"].truck_id,
                TruckUpdate(),
            )
        assert error.value.status_code == 400

    def test_retired_truck_cannot_be_updated(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                fleet_trucks["retired"].truck_id,
                TruckUpdate(truck_type="Tipper XL"),
            )
        assert error.value.status_code == 409

    @pytest.mark.parametrize(
        "change", [{"capacity_kg": 5000}, {"body_type": models.BodyType.BOX}]
    )
    def test_allocated_truck_load_is_locked(
        self, db_session, fleet_company, fleet_manager, allocated_truck, change
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                allocated_truck["truck"].truck_id,
                TruckUpdate(**change),
            )
        assert error.value.status_code == 409
        assert audit_events(db_session, "truck_updated") == []

    def test_allocated_truck_other_fields_can_change(
        self, db_session, fleet_company, fleet_manager, allocated_truck
    ):
        truck = truck_service.update_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            allocated_truck["truck"].truck_id,
            TruckUpdate(current_location="Kapiri Mposhi", maintenance_per_km="2.75"),
        )
        assert truck.current_location == "Kapiri Mposhi"

    def test_rival_cannot_update(
        self, db_session, rival_company, rival_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_truck(
                db_session,
                rival_company.company_id,
                rival_manager.user_id,
                fleet_trucks["flatbed"].truck_id,
                TruckUpdate(truck_type="Hijacked"),
            )
        assert error.value.status_code == 404
        assert fleet_trucks["flatbed"].truck_type == "Rigid"


class TestAvailabilityService:
    def test_mark_unavailable_with_return_date(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        back_on = datetime.now(timezone.utc) + timedelta(days=3)
        truck = truck_service.update_availability(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["flatbed"].truck_id,
            TruckAvailabilityUpdate(
                availability_status="unavailable",
                available_from=back_on,
                current_location="Workshop",
            ),
        )

        assert truck.availability_status == models.AvailabilityStatus.UNAVAILABLE
        assert truck.available_from is not None
        assert truck.current_location == "Workshop"
        event = audit_events(db_session, "truck_availability_changed")[0]
        assert event.details == {"from": "available", "to": "unavailable"}
        assert event.company_id == fleet_company.company_id

    def test_mark_available_again(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck = truck_service.update_availability(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["workshop"].truck_id,
            TruckAvailabilityUpdate(availability_status="available"),
        )
        assert truck.availability_status == models.AvailabilityStatus.AVAILABLE

    def test_location_untouched_when_not_sent(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck = truck_service.update_availability(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["flatbed"].truck_id,
            TruckAvailabilityUpdate(availability_status="unavailable"),
        )
        assert truck.current_location == "Lusaka"

    def test_allocated_truck_cannot_become_available(
        self, db_session, fleet_company, fleet_manager, allocated_truck
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_availability(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                allocated_truck["truck"].truck_id,
                TruckAvailabilityUpdate(availability_status="available"),
            )
        assert error.value.status_code == 409

    def test_allocated_truck_freed_after_shipment_cancelled(
        self, db_session, fleet_company, fleet_manager, allocated_truck
    ):
        allocated_truck["shipment"].status = models.ShipmentStatus.CANCELLED
        db_session.commit()

        truck = truck_service.update_availability(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            allocated_truck["truck"].truck_id,
            TruckAvailabilityUpdate(availability_status="available"),
        )
        assert truck.availability_status == models.AvailabilityStatus.AVAILABLE

    def test_retired_truck_availability_is_frozen(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.update_availability(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                fleet_trucks["retired"].truck_id,
                TruckAvailabilityUpdate(availability_status="available"),
            )
        assert error.value.status_code == 409


class TestRetireService:
    def test_retire_truck_with_reason(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck = truck_service.retire_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["workshop"].truck_id,
            TruckRetireRequest(reason="Chassis cracked"),
        )

        assert truck.availability_status == models.AvailabilityStatus.RETIRED
        event = audit_events(db_session, "truck_retired")[0]
        assert event.details == {"reason": "Chassis cracked"}
        assert event.entity_id == truck.truck_id

    def test_retire_without_reason_logs_no_details(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        truck_service.retire_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            fleet_trucks["flatbed"].truck_id,
            TruckRetireRequest(),
        )
        assert audit_events(db_session, "truck_retired")[0].details is None

    def test_retired_truck_keeps_its_history(
        self, db_session, fleet_company, fleet_manager, allocated_truck
    ):
        allocated_truck["shipment"].status = models.ShipmentStatus.CANCELLED
        db_session.commit()

        truck = truck_service.retire_truck(
            db_session,
            fleet_company.company_id,
            fleet_manager.user_id,
            allocated_truck["truck"].truck_id,
            TruckRetireRequest(),
        )
        assert len(truck.reservations) == 1
        assert len(truck.shipment_matches) == 1

    def test_cannot_retire_twice(
        self, db_session, fleet_company, fleet_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.retire_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                fleet_trucks["retired"].truck_id,
                TruckRetireRequest(),
            )
        assert error.value.status_code == 409

    def test_cannot_retire_allocated_truck(
        self, db_session, fleet_company, fleet_manager, allocated_truck
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.retire_truck(
                db_session,
                fleet_company.company_id,
                fleet_manager.user_id,
                allocated_truck["truck"].truck_id,
                TruckRetireRequest(),
            )
        assert error.value.status_code == 409
        assert audit_events(db_session, "truck_retired") == []

    def test_rival_cannot_retire(
        self, db_session, rival_company, rival_manager, fleet_trucks
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.retire_truck(
                db_session,
                rival_company.company_id,
                rival_manager.user_id,
                fleet_trucks["flatbed"].truck_id,
                TruckRetireRequest(),
            )
        assert error.value.status_code == 404


class TestAllocationService:
    def test_allocated_truck_shows_shipment(
        self, db_session, fleet_company, allocated_truck
    ):
        result = truck_service.get_truck_allocation(
            db_session, fleet_company.company_id, allocated_truck["truck"].truck_id
        )

        assert result.allocation_status == "allocated"
        shipment = result.allocated_shipment
        assert shipment.shipment_id == allocated_truck["shipment"].shipment_id
        assert shipment.origin_address == "Kitwe, Zambia"
        assert shipment.weight_kg == 25000.0
        assert shipment.shipment_status == models.ShipmentStatus.CONFIRMED

    @pytest.mark.parametrize(
        "key, expected",
        [("flatbed", "available"), ("workshop", "unavailable"), ("retired", "retired")],
    )
    def test_free_trucks_report_their_status(
        self, db_session, fleet_company, fleet_trucks, key, expected
    ):
        result = truck_service.get_truck_allocation(
            db_session, fleet_company.company_id, fleet_trucks[key].truck_id
        )
        assert result.allocation_status == expected
        assert result.allocated_shipment is None

    def test_overview_covers_every_active_truck(
        self, db_session, fleet_company, fleet_trucks, allocated_truck
    ):
        rows = truck_service.list_truck_allocations(
            db_session, fleet_company.company_id
        )
        by_plate = {row.plate_number: row.allocation_status for row in rows}
        assert by_plate == {
            "BAA 1001": "available",
            "BAA 1002": "available",
            "BAA 1003": "unavailable",
            "BAA 1004": "allocated",
        }

    def test_rival_cannot_see_allocation(
        self, db_session, rival_company, allocated_truck
    ):
        with pytest.raises(HTTPException) as error:
            truck_service.get_truck_allocation(
                db_session, rival_company.company_id, allocated_truck["truck"].truck_id
            )
        assert error.value.status_code == 404


@pytest.fixture
def api(db_session):
    """Returns a function that builds a client acting as a given user.

    Instead of a real login, the auth dependencies are swapped for the mock
    user and company, the same way the app would see them after
    Helen's login + verification checks pass.
    """

    def as_user(user, company):
        def override_db():
            yield db_session

        def mock_verified_company():
            if company.verification_status != models.VerificationStatus.VERIFIED:
                raise HTTPException(status_code=403, detail="Company is not verified")
            return company

        def mock_fleet_manager():
            if user.role != models.UserRole.FLEET_MANAGER:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_verified_company] = mock_verified_company
        app.dependency_overrides[truck_router.fleet_manager] = mock_fleet_manager
        return TestClient(app)

    yield as_user
    app.dependency_overrides.clear()


class TestTruckRoutes:
    def test_register_truck_201(self, api, fleet_manager, fleet_company):
        response = api(fleet_manager, fleet_company).post(
            "/trucks", json=truck_payload()
        )
        assert response.status_code == 201
        assert response.json()["plate_number"] == "BAD 4321"

    def test_register_invalid_body_422(self, api, fleet_manager, fleet_company):
        response = api(fleet_manager, fleet_company).post(
            "/trucks", json=truck_payload(capacity_kg=-5)
        )
        assert response.status_code == 422

    def test_shipper_gets_403(self, api, shipper_user, shipper_company):
        client = api(shipper_user, shipper_company)
        assert client.get("/trucks").status_code == 403
        assert client.post("/trucks", json=truck_payload()).status_code == 403

    def test_unverified_company_gets_403(
        self, api, unverified_manager, unverified_company
    ):
        response = api(unverified_manager, unverified_company).get("/trucks")
        assert response.status_code == 403

    def test_no_login_gets_401(self, db_session):
        app.dependency_overrides[get_db] = lambda: (yield db_session)
        try:
            assert TestClient(app).get("/trucks").status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_list_with_filters(self, api, fleet_manager, fleet_company, fleet_trucks):
        client = api(fleet_manager, fleet_company)
        assert len(client.get("/trucks").json()) == 3
        assert len(client.get("/trucks?include_retired=true").json()) == 4
        boxes = client.get("/trucks?body_type=box").json()
        assert [t["plate_number"] for t in boxes] == ["BAA 1003"]
        assert client.get("/trucks?body_type=bus").status_code == 422

    def test_detail_update_availability_retire_flow(
        self, api, fleet_manager, fleet_company, fleet_trucks, db_session
    ):
        client = api(fleet_manager, fleet_company)
        truck_id = fleet_trucks["reefer"].truck_id

        assert client.get(f"/trucks/{truck_id}").status_code == 200
        assert (
            client.patch(f"/trucks/{truck_id}", json={"capacity_kg": 14000}).json()[
                "capacity_kg"
            ]
            == 14000
        )
        assert (
            client.patch(
                f"/trucks/{truck_id}/availability",
                json={"availability_status": "unavailable"},
            ).json()["availability_status"]
            == "unavailable"
        )
        assert (
            client.post(f"/trucks/{truck_id}/retire", json={"reason": "Sold"}).json()[
                "availability_status"
            ]
            == "retired"
        )
        assert client.post(f"/trucks/{truck_id}/retire").status_code == 409

        actions = [e.action_type for e in audit_events(db_session, entity_id=truck_id)]
        assert actions == [
            "truck_updated",
            "truck_availability_changed",
            "truck_retired",
        ]

    def test_allocation_routes(
        self, api, fleet_manager, fleet_company, allocated_truck
    ):
        client = api(fleet_manager, fleet_company)
        truck_id = allocated_truck["truck"].truck_id

        detail = client.get(f"/trucks/{truck_id}/allocation")
        assert detail.status_code == 200
        assert detail.json()["allocation_status"] == "allocated"

        overview = client.get("/trucks/allocations")
        assert overview.status_code == 200
        assert overview.json()[0]["plate_number"] == "BAA 1004"

    def test_rival_gets_404_everywhere(
        self, api, rival_manager, rival_company, fleet_trucks
    ):
        client = api(rival_manager, rival_company)
        truck_id = fleet_trucks["flatbed"].truck_id
        assert client.get(f"/trucks/{truck_id}").status_code == 404
        assert (
            client.patch(f"/trucks/{truck_id}", json={"truck_type": "X1"}).status_code
            == 404
        )
        assert client.post(f"/trucks/{truck_id}/retire").status_code == 404
        assert client.get(f"/trucks/{truck_id}/allocation").status_code == 404

    def test_bad_ids(self, api, fleet_manager, fleet_company):
        client = api(fleet_manager, fleet_company)
        assert client.get(f"/trucks/{uuid.uuid4()}").status_code == 404
        assert client.get("/trucks/not-a-uuid").status_code == 422
