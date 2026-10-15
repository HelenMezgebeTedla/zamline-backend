from datetime import datetime, timezone
from decimal import Decimal

import models
import pytest

from schemas.shipment_matches import FleetMatchResponse
from services.shipment_matches import (
    FleetCompanyNotEligibleError,
    generate_matches_for_fleet_company,
    list_matches_for_fleet_company,
)


PICKUP_TIME = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)


def create_company(
    db_session,
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
    )
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


def create_user(db_session, company, suffix, role):
    user = models.User(
        company_id=company.company_id,
        first_name="Test",
        last_name=suffix,
        email=f"user-{suffix.lower()}@example.com",
        password_hash="hashed-password",
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def create_truck(
    db_session,
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
    db_session.add(truck)
    db_session.commit()
    db_session.refresh(truck)
    return truck


def create_shipment(
    db_session,
    company,
    user,
    suffix,
    weight_kg=18_000,
    required_body_type=models.BodyType.FLATBED,
    status=models.ShipmentStatus.OPEN,
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
    )
    db_session.add(shipment)
    db_session.commit()
    db_session.refresh(shipment)
    return shipment


def create_verified_fleet(db_session, suffix="FLEET"):
    return create_company(db_session, suffix)


def create_shipper_with_user(db_session, suffix="SHIPPER"):
    company = create_company(
        db_session,
        suffix,
        company_type=models.CompanyType.SHIPPER,
    )
    user = create_user(db_session, company, suffix, models.UserRole.SHIPPER)
    return company, user


def test_matching_creates_match_for_compatible_available_truck(db_session):
    fleet = create_verified_fleet(db_session, "F1")
    truck = create_truck(db_session, fleet, "F1")
    shipper, shipper_user = create_shipper_with_user(db_session, "S1")
    shipment = create_shipment(db_session, shipper, shipper_user, "S1")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert len(matches) == 1
    assert matches[0].shipment_id == shipment.shipment_id
    assert matches[0].truck_id == truck.truck_id
    assert matches[0].manager_decision == models.ManagerDecision.PENDING
    assert matches[0].proposed_amount == Decimal("18500.00")


def test_matching_accepts_exact_capacity(db_session):
    fleet = create_verified_fleet(db_session, "F2")
    create_truck(db_session, fleet, "F2", capacity_kg=18_000)
    shipper, shipper_user = create_shipper_with_user(db_session, "S2")
    create_shipment(db_session, shipper, shipper_user, "S2", weight_kg=18_000)

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert len(matches) == 1


def test_matching_rejects_insufficient_capacity(db_session):
    fleet = create_verified_fleet(db_session, "F3")
    create_truck(db_session, fleet, "F3", capacity_kg=17_999)
    shipper, shipper_user = create_shipper_with_user(db_session, "S3")
    create_shipment(db_session, shipper, shipper_user, "S3", weight_kg=18_000)

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert matches == []


def test_matching_rejects_wrong_body_type(db_session):
    fleet = create_verified_fleet(db_session, "F4")
    create_truck(
        db_session,
        fleet,
        "F4",
        body_type=models.BodyType.TANKER,
    )
    shipper, shipper_user = create_shipper_with_user(db_session, "S4")
    create_shipment(db_session, shipper, shipper_user, "S4")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert matches == []


def test_matching_rejects_unavailable_truck(db_session):
    fleet = create_verified_fleet(db_session, "F5")
    create_truck(
        db_session,
        fleet,
        "F5",
        availability=models.AvailabilityStatus.UNAVAILABLE,
    )
    shipper, shipper_user = create_shipper_with_user(db_session, "S5")
    create_shipment(db_session, shipper, shipper_user, "S5")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert matches == []


def test_matching_rejects_non_open_shipment(db_session):
    fleet = create_verified_fleet(db_session, "F6")
    create_truck(db_session, fleet, "F6")
    shipper, shipper_user = create_shipper_with_user(db_session, "S6")
    create_shipment(
        db_session,
        shipper,
        shipper_user,
        "S6",
        status=models.ShipmentStatus.CONFIRMED,
    )

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert matches == []


def test_matching_rejects_unverified_fleet_company(db_session):
    fleet = create_company(
        db_session,
        "F7",
        verification_status=models.VerificationStatus.PENDING,
    )
    create_truck(db_session, fleet, "F7")
    shipper, shipper_user = create_shipper_with_user(db_session, "S7")
    create_shipment(db_session, shipper, shipper_user, "S7")

    with pytest.raises(FleetCompanyNotEligibleError):
        generate_matches_for_fleet_company(db_session, fleet.company_id)


def test_matching_does_not_match_own_company_shipment(db_session):
    fleet = create_verified_fleet(db_session, "F8")
    fleet_user = create_user(
        db_session,
        fleet,
        "F8",
        models.UserRole.FLEET_MANAGER,
    )
    create_truck(db_session, fleet, "F8")
    create_shipment(db_session, fleet, fleet_user, "F8")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert matches == []


def test_matching_is_idempotent(db_session):
    fleet = create_verified_fleet(db_session, "F9")
    create_truck(db_session, fleet, "F9")
    shipper, shipper_user = create_shipper_with_user(db_session, "S9")
    create_shipment(db_session, shipper, shipper_user, "S9")

    first_run = generate_matches_for_fleet_company(db_session, fleet.company_id)
    second_run = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert len(first_run) == 1
    assert len(second_run) == 1
    assert first_run[0].match_id == second_run[0].match_id
    assert db_session.query(models.ShipmentMatch).count() == 1


def test_matching_creates_one_match_per_eligible_truck(db_session):
    fleet = create_verified_fleet(db_session, "F10")
    create_truck(db_session, fleet, "F10A")
    create_truck(db_session, fleet, "F10B", capacity_kg=25_000)
    shipper, shipper_user = create_shipper_with_user(db_session, "S10")
    create_shipment(db_session, shipper, shipper_user, "S10")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert len(matches) == 2
    assert len({match.truck_id for match in matches}) == 2


def test_matching_allows_one_truck_to_match_multiple_open_shipments(db_session):
    fleet = create_verified_fleet(db_session, "F11")
    truck = create_truck(db_session, fleet, "F11")
    shipper, shipper_user = create_shipper_with_user(db_session, "S11")
    first = create_shipment(db_session, shipper, shipper_user, "S11A")
    second = create_shipment(db_session, shipper, shipper_user, "S11B")

    matches = generate_matches_for_fleet_company(db_session, fleet.company_id)

    assert len(matches) == 2
    assert {match.shipment_id for match in matches} == {
        first.shipment_id,
        second.shipment_id,
    }
    assert {match.truck_id for match in matches} == {truck.truck_id}


def test_matching_does_not_populate_cost_or_ai_fields(db_session):
    fleet = create_verified_fleet(db_session, "F12")
    create_truck(db_session, fleet, "F12")
    shipper, shipper_user = create_shipper_with_user(db_session, "S12")
    create_shipment(db_session, shipper, shipper_user, "S12")

    match = generate_matches_for_fleet_company(db_session, fleet.company_id)[0]

    assert match.distance_km is None
    assert match.duration is None
    assert match.fuel_cost is None
    assert match.driver_cost is None
    assert match.toll_cost is None
    assert match.maintenance_cost is None
    assert match.other_cost is None
    assert match.estimated_total_cost is None
    assert match.estimated_margin is None
    assert match.outcome is None
    assert match.ai_explanation is None


def test_response_schema_exposes_only_matching_information(db_session):
    fleet = create_verified_fleet(db_session, "F13")
    create_truck(db_session, fleet, "F13")
    shipper, shipper_user = create_shipper_with_user(db_session, "S13")
    create_shipment(db_session, shipper, shipper_user, "S13")

    match = generate_matches_for_fleet_company(db_session, fleet.company_id)[0]
    response = FleetMatchResponse.model_validate(match).model_dump()

    assert "fuel_cost" not in response
    assert "estimated_total_cost" not in response
    assert "estimated_margin" not in response
    assert "ai_explanation" not in response
    assert "company" not in response
    assert "company_id" not in response["truck"]
    assert "company_id" not in response["shipment"]


def test_match_listing_is_isolated_by_fleet_company(db_session):
    fleet_a = create_verified_fleet(db_session, "F14A")
    fleet_b = create_verified_fleet(db_session, "F14B")
    truck_a = create_truck(db_session, fleet_a, "F14A")
    truck_b = create_truck(db_session, fleet_b, "F14B")
    shipper, shipper_user = create_shipper_with_user(db_session, "S14")
    create_shipment(db_session, shipper, shipper_user, "S14")

    generate_matches_for_fleet_company(db_session, fleet_a.company_id)
    generate_matches_for_fleet_company(db_session, fleet_b.company_id)

    matches_a = list_matches_for_fleet_company(db_session, fleet_a.company_id)
    matches_b = list_matches_for_fleet_company(db_session, fleet_b.company_id)

    assert len(matches_a) == 1
    assert len(matches_b) == 1
    assert matches_a[0].truck_id == truck_a.truck_id
    assert matches_b[0].truck_id == truck_b.truck_id
    assert matches_a[0].match_id != matches_b[0].match_id
