from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.routing import RouteSummary

PICKUP_TIME = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)


def create_test_engine():
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
    return engine


def create_test_sessionmaker(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_company(
    db,
    suffix,
    company_type=models.CompanyType.FLEET,
    verification_status=models.VerificationStatus.VERIFIED,
):
    company = models.Company(
        company_type=company_type,
        business_name=f"Company {suffix}",
        registration_number=f"REG-{suffix}",
        company_email=f"{suffix.lower()}@example.com",
        phone_number="+260211000000",
        verification_status=verification_status,
        fuel_price_per_litre=Decimal("27.50"),
        driver_daily_allowance=Decimal("450.00"),
        toll_assumption=Decimal("120.00"),
        other_costs=Decimal("80.00"),
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def create_user(
    db,
    company,
    suffix,
    role=models.UserRole.FLEET_MANAGER,
    is_active=True,
):
    user = models.User(
        company_id=company.company_id,
        first_name="Test",
        last_name=suffix,
        email=f"user-{suffix.lower()}@example.com",
        password_hash="hashed-password",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_fleet_manager(
    db,
    suffix,
    verification_status=models.VerificationStatus.VERIFIED,
):
    company = create_company(db, suffix, verification_status=verification_status)
    user = create_user(db, company, suffix)
    return company, user


def create_shipper(db, suffix):
    company = create_company(
        db,
        suffix,
        company_type=models.CompanyType.SHIPPER,
    )
    user = create_user(
        db,
        company,
        suffix,
        role=models.UserRole.SHIPPER,
    )
    return company, user


def create_truck(
    db,
    company,
    suffix,
    capacity_kg=20_000,
    body_type=models.BodyType.FLATBED,
    availability=models.AvailabilityStatus.AVAILABLE,
):
    truck = models.Truck(
        company_id=company.company_id,
        plate_number=f"TRK-{suffix}",
        truck_type="Heavy Duty",
        body_type=body_type,
        capacity_kg=capacity_kg,
        fuel_consumption_l_per_100km=30.0,
        maintenance_per_km=Decimal("2.50"),
        availability_status=availability,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)
    return truck


def create_shipment(
    db,
    company,
    user,
    suffix,
    weight_kg=18_000,
    required_body_type=models.BodyType.FLATBED,
    status=models.ShipmentStatus.OPEN,
    special_requirements=None,
):
    shipment = models.Shipment(
        company_id=company.company_id,
        user_id=user.user_id,
        origin_address=f"Origin {suffix}",
        origin_latitude=-12.8024,
        origin_longitude=28.2132,
        destination_address=f"Destination {suffix}",
        destination_latitude=-15.3875,
        destination_longitude=28.3228,
        cargo_type="Copper",
        weight_kg=weight_kg,
        required_body_type=required_body_type,
        pickup_time=PICKUP_TIME,
        proposed_amount=Decimal("18500.00"),
        status=status,
        special_requirements=special_requirements,
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


STUB_ROUTE = RouteSummary(
    distance_km=320.0,
    duration_minutes=270,
)
