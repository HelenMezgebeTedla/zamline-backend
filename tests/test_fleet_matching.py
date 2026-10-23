import uuid
from decimal import Decimal

import pytest

import models
from fleet_helpers import (
    create_company,
    create_fleet_manager,
    create_shipment,
    create_shipper,
    create_test_engine,
    create_test_sessionmaker,
    create_truck,
    create_user,
)
from schemas.shipment_matches import FleetMatchResponse
from services.shipment_matches import (
    ActorNotAllowedError,
    ActorNotFoundError,
    FleetCompanyNotEligibleError,
    generate_matches_for_fleet_manager,
    list_opportunities_for_fleet_manager,
)


@pytest.fixture
def db():
    engine = create_test_engine()
    session = create_test_sessionmaker(engine)()
    yield session
    session.close()
    engine.dispose()


def setup_one_match(db, suffix="A"):
    fleet, manager = create_fleet_manager(db, f"F{suffix}")
    truck = create_truck(db, fleet, f"F{suffix}")
    shipper, shipper_user = create_shipper(db, f"S{suffix}")
    shipment = create_shipment(db, shipper, shipper_user, f"S{suffix}")
    matches = generate_matches_for_fleet_manager(db, manager.user_id)
    return manager, truck, shipment, matches


def test_matching_creates_match_for_compatible_available_truck(db):
    manager, truck, shipment, matches = setup_one_match(db)

    assert len(matches) == 1
    assert matches[0].shipment_id == shipment.shipment_id
    assert matches[0].truck_id == truck.truck_id
    assert matches[0].manager_decision == models.ManagerDecision.PENDING
    assert matches[0].proposed_amount == Decimal("18500.00")


def test_matching_accepts_exact_capacity(db):
    fleet, manager = create_fleet_manager(db, "F2")
    create_truck(db, fleet, "F2", capacity_kg=18_000)
    shipper, shipper_user = create_shipper(db, "S2")
    create_shipment(db, shipper, shipper_user, "S2", weight_kg=18_000)

    matches = generate_matches_for_fleet_manager(db, manager.user_id)

    assert len(matches) == 1


def test_matching_rejects_insufficient_capacity(db):
    fleet, manager = create_fleet_manager(db, "F3")
    create_truck(db, fleet, "F3", capacity_kg=17_999)
    shipper, shipper_user = create_shipper(db, "S3")
    create_shipment(db, shipper, shipper_user, "S3", weight_kg=18_000)

    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_matching_rejects_wrong_body_type(db):
    fleet, manager = create_fleet_manager(db, "F4")
    create_truck(db, fleet, "F4", body_type=models.BodyType.TANKER)
    shipper, shipper_user = create_shipper(db, "S4")
    create_shipment(db, shipper, shipper_user, "S4")

    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_matching_rejects_unavailable_truck(db):
    fleet, manager = create_fleet_manager(db, "F5")
    create_truck(db, fleet, "F5", availability=models.AvailabilityStatus.UNAVAILABLE)
    shipper, shipper_user = create_shipper(db, "S5")
    create_shipment(db, shipper, shipper_user, "S5")

    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_matching_rejects_non_open_shipment(db):
    fleet, manager = create_fleet_manager(db, "F6")
    create_truck(db, fleet, "F6")
    shipper, shipper_user = create_shipper(db, "S6")
    create_shipment(
        db, shipper, shipper_user, "S6", status=models.ShipmentStatus.CONFIRMED
    )

    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_matching_does_not_match_own_company_shipment(db):
    fleet, manager = create_fleet_manager(db, "F8")
    create_truck(db, fleet, "F8")
    create_shipment(db, fleet, manager, "F8")

    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_matching_is_idempotent(db):
    manager, truck, shipment, first_run = setup_one_match(db)

    second_run = generate_matches_for_fleet_manager(db, manager.user_id)

    assert len(first_run) == 1
    assert len(second_run) == 1
    assert first_run[0].match_id == second_run[0].match_id
    assert db.query(models.ShipmentMatch).count() == 1


def test_matching_creates_one_match_per_eligible_truck(db):
    fleet, manager = create_fleet_manager(db, "F10")
    create_truck(db, fleet, "F10A")
    create_truck(db, fleet, "F10B", capacity_kg=25_000)
    shipper, shipper_user = create_shipper(db, "S10")
    create_shipment(db, shipper, shipper_user, "S10")

    matches = generate_matches_for_fleet_manager(db, manager.user_id)

    assert len(matches) == 2
    assert len({match.truck_id for match in matches}) == 2


def test_matching_allows_one_truck_to_match_multiple_open_shipments(db):
    fleet, manager = create_fleet_manager(db, "F11")
    truck = create_truck(db, fleet, "F11")
    shipper, shipper_user = create_shipper(db, "S11")
    first = create_shipment(db, shipper, shipper_user, "S11A")
    second = create_shipment(db, shipper, shipper_user, "S11B")

    matches = generate_matches_for_fleet_manager(db, manager.user_id)

    assert len(matches) == 2
    assert {match.shipment_id for match in matches} == {
        first.shipment_id,
        second.shipment_id,
    }
    assert {match.truck_id for match in matches} == {truck.truck_id}


def test_matching_does_not_populate_cost_or_ai_fields(db):
    manager, truck, shipment, matches = setup_one_match(db)
    match = matches[0]

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


def test_response_schema_exposes_only_matching_information(db):
    manager, truck, shipment, matches = setup_one_match(db)

    response = FleetMatchResponse.model_validate(matches[0]).model_dump()

    assert "fuel_cost" not in response
    assert "estimated_total_cost" not in response
    assert "estimated_margin" not in response
    assert "ai_explanation" not in response
    assert "company" not in response
    assert "company_id" not in response["truck"]
    assert "company_id" not in response["shipment"]


def test_match_listing_is_isolated_by_fleet_company(db):
    fleet_a, manager_a = create_fleet_manager(db, "F14A")
    fleet_b, manager_b = create_fleet_manager(db, "F14B")
    truck_a = create_truck(db, fleet_a, "F14A")
    truck_b = create_truck(db, fleet_b, "F14B")
    shipper, shipper_user = create_shipper(db, "S14")
    create_shipment(db, shipper, shipper_user, "S14")

    generate_matches_for_fleet_manager(db, manager_a.user_id)
    generate_matches_for_fleet_manager(db, manager_b.user_id)

    matches_a = list_opportunities_for_fleet_manager(db, manager_a.user_id)
    matches_b = list_opportunities_for_fleet_manager(db, manager_b.user_id)

    assert [match.truck_id for match in matches_a] == [truck_a.truck_id]
    assert [match.truck_id for match in matches_b] == [truck_b.truck_id]


def test_nonexistent_actor_is_rejected(db):
    with pytest.raises(ActorNotFoundError):
        generate_matches_for_fleet_manager(db, uuid.uuid4())


def test_inactive_fleet_manager_is_rejected(db):
    fleet = create_company(db, "F20")
    manager = create_user(db, fleet, "F20", is_active=False)

    with pytest.raises(ActorNotAllowedError):
        list_opportunities_for_fleet_manager(db, manager.user_id)


def test_shipper_cannot_use_fleet_matching(db):
    shipper, shipper_user = create_shipper(db, "S21")

    with pytest.raises(ActorNotAllowedError):
        generate_matches_for_fleet_manager(db, shipper_user.user_id)


def test_unverified_fleet_company_is_rejected(db):
    fleet, manager = create_fleet_manager(
        db, "F22", verification_status=models.VerificationStatus.PENDING
    )
    create_truck(db, fleet, "F22")
    shipper, shipper_user = create_shipper(db, "S22")
    create_shipment(db, shipper, shipper_user, "S22")

    with pytest.raises(FleetCompanyNotEligibleError):
        generate_matches_for_fleet_manager(db, manager.user_id)


def test_fleet_manager_role_in_shipper_company_is_rejected(db):
    shipper, shipper_user = create_shipper(db, "S23")
    wrong_user = create_user(db, shipper, "S23X", role=models.UserRole.FLEET_MANAGER)

    with pytest.raises(FleetCompanyNotEligibleError):
        list_opportunities_for_fleet_manager(db, wrong_user.user_id)


def test_truck_made_unavailable_removes_opportunity(db):
    manager, truck, shipment, matches = setup_one_match(db)

    truck.availability_status = models.AvailabilityStatus.UNAVAILABLE
    db.commit()

    assert list_opportunities_for_fleet_manager(db, manager.user_id) == []


def test_changed_truck_body_type_removes_opportunity(db):
    manager, truck, shipment, matches = setup_one_match(db)

    truck.body_type = models.BodyType.TANKER
    db.commit()

    assert list_opportunities_for_fleet_manager(db, manager.user_id) == []


def test_reduced_truck_capacity_removes_opportunity(db):
    manager, truck, shipment, matches = setup_one_match(db)

    truck.capacity_kg = 1_000
    db.commit()

    assert list_opportunities_for_fleet_manager(db, manager.user_id) == []


@pytest.mark.parametrize(
    "decision",
    [models.ManagerDecision.CLOSED, models.ManagerDecision.ACCEPTED],
)
def test_non_pending_matches_never_appear(db, decision):
    manager, truck, shipment, matches = setup_one_match(db)

    matches[0].manager_decision = decision
    db.commit()

    assert list_opportunities_for_fleet_manager(db, manager.user_id) == []
    assert generate_matches_for_fleet_manager(db, manager.user_id) == []


def test_confirmed_shipment_does_not_appear(db):
    manager, truck, shipment, matches = setup_one_match(db)

    shipment.status = models.ShipmentStatus.CONFIRMED
    db.commit()

    assert list_opportunities_for_fleet_manager(db, manager.user_id) == []
