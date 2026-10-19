import os

os.environ.setdefault("JWT_SECRET", "ci-only-secret-key-0123456789-abcdef")

import itertools

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base, get_db
import models

SAMPLE_PICKUP_TIME = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.rollback()
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def sample_company(db_session):
    company = models.Company(
        company_type=models.CompanyType.SHIPPER,
        business_name="Test Company",
        registration_number="REG123456",
        company_email="test@company.com",
        phone_number="+1234567890",
    )
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


@pytest.fixture
def sample_fleet_company(db_session):
    company = models.Company(
        company_type=models.CompanyType.FLEET,
        business_name="Test Fleet Co",
        registration_number="REG789012",
        company_email="fleet@company.com",
        phone_number="+0987654321",
    )
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


@pytest.fixture
def sample_user(db_session, sample_company):
    user = models.User(
        company_id=sample_company.company_id,
        first_name="John",
        last_name="Doe",
        email="john.doe@test.com",
        password_hash="hashed_password_123",
        role=models.UserRole.SHIPPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_fleet_user(db_session, sample_fleet_company):
    user = models.User(
        company_id=sample_fleet_company.company_id,
        first_name="Jane",
        last_name="Smith",
        email="jane.smith@fleet.com",
        password_hash="hashed_password_456",
        role=models.UserRole.FLEET_MANAGER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_truck(db_session, sample_fleet_company):
    truck = models.Truck(
        company_id=sample_fleet_company.company_id,
        plate_number="ABC-1234",
        truck_type="Heavy Duty",
        body_type=models.BodyType.FLATBED,
        capacity_kg=10000.0,
        fuel_consumption_l_per_100km=30.0,
        maintenance_per_km=2.50,
    )
    db_session.add(truck)
    db_session.commit()
    db_session.refresh(truck)
    return truck


@pytest.fixture
def sample_shipment(db_session, sample_company, sample_user):
    shipment = models.Shipment(
        company_id=sample_company.company_id,
        user_id=sample_user.user_id,
        origin_address="123 Origin St, City A",
        origin_latitude=40.7128,
        origin_longitude=-74.0060,
        destination_address="456 Dest Ave, City B",
        destination_latitude=34.0522,
        destination_longitude=-118.2437,
        cargo_type="Electronics",
        weight_kg=5000.0,
        required_body_type=models.BodyType.FLATBED,
        pickup_time=SAMPLE_PICKUP_TIME,
        proposed_amount=15000.00,
    )
    db_session.add(shipment)
    db_session.commit()
    db_session.refresh(shipment)
    return shipment


@pytest.fixture
def sample_match(db_session, sample_shipment, sample_truck, sample_fleet_user):
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
        ai_explanation="Good match based on location and capacity",
    )
    db_session.add(match)
    db_session.commit()
    db_session.refresh(match)
    return match


@pytest.fixture
def sample_reservation(
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
    return reservation


@pytest.fixture
def mock_otp_email(monkeypatch):
    captured: list[str] = []

    def _capture(_: str, code: str) -> None:
        captured.append(code)

    monkeypatch.setattr("services.otp.send_otp_email", _capture)
    monkeypatch.setattr("services.otp.send_password_reset_email", _capture)
    return captured


@pytest.fixture
def client(db_session, mock_otp_email):
    from main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as api_client:
        yield api_client

    app.dependency_overrides.clear()


@pytest.fixture
def registration_payload():
    sequence = itertools.count(1)

    def _build(company_type: str = "shipper", **overrides) -> dict:
        number = next(sequence)
        payload = {
            "business_name": f"Test Business {number}",
            "registration_number": f"1201{number:06d}",
            "company_email": f"owner{number}@zamline-tests.com",
            "phone_number": "+260971234567",
            "company_type": company_type,
            "first_name": "Test",
            "last_name": "Owner",
            "password": "StrongPass123",
        }
        payload.update(overrides)
        return payload

    return _build


@pytest.fixture
def register_and_login(client, mock_otp_email, registration_payload):
    def _register(company_type: str = "shipper", **overrides) -> dict:
        payload = registration_payload(company_type, **overrides)
        registered = client.post("/users/register", json=payload)
        assert registered.status_code == 201, registered.text

        login = client.post(
            "/users/login",
            json={"email": payload["company_email"], "password": payload["password"]},
        )
        assert login.status_code == 200, login.text

        verified = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": mock_otp_email[-1]},
        )
        assert verified.status_code == 200, verified.text

        body = registered.json()
        return {
            "headers": {"Authorization": f"Bearer {verified.json()['access_token']}"},
            "payload": payload,
            "company_id": body["company"]["company_id"],
            "user_id": body["user"]["user_id"],
        }

    return _register
