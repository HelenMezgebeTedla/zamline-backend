import uuid
from types import SimpleNamespace

import pytest

import models
from fleet_helpers import (
    create_fleet_manager,
    create_shipment,
    create_shipper,
    create_test_engine,
    create_test_sessionmaker,
    create_truck,
)
from schemas.shipment_matches import MatchDecisionResponse
from services.shipment_matches import (
    ActorNotAllowedError,
    MatchAccessDeniedError,
    MatchNotFoundError,
    ShipmentNoLongerAvailableError,
    accept_match,
    generate_matches_for_fleet_manager,
    list_opportunities_for_fleet_manager,
    skip_match,
)


@pytest.fixture
def db():
    engine = create_test_engine()
    session = create_test_sessionmaker(engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def market(db):
    fleet_a, manager_a = create_fleet_manager(db, "FA")
    truck_a = create_truck(db, fleet_a, "FA")
    fleet_b, manager_b = create_fleet_manager(db, "FB")
    create_truck(db, fleet_b, "FB")
    shipper, shipper_user = create_shipper(db, "SH")
    shipment = create_shipment(db, shipper, shipper_user, "SH")

    match_a = generate_matches_for_fleet_manager(db, manager_a.user_id)[0]
    match_b = generate_matches_for_fleet_manager(db, manager_b.user_id)[0]

    return SimpleNamespace(
        manager_a=manager_a,
        truck_a=truck_a,
        match_a=match_a,
        manager_b=manager_b,
        match_b=match_b,
        shipper_user=shipper_user,
        shipment=shipment,
    )


def assert_still_pending(db, match):
    db.expire_all()
    assert match.manager_decision == models.ManagerDecision.PENDING
    assert match.user_id is None
    assert match.decided_at is None


@pytest.mark.parametrize(
    "decide, expected",
    [
        (accept_match, models.ManagerDecision.ACCEPTED),
        (skip_match, models.ManagerDecision.DECLINED),
    ],
)
def test_fleet_manager_decision_is_recorded(db, market, decide, expected):
    decided = decide(db, market.manager_a.user_id, market.match_a.match_id)

    response = MatchDecisionResponse.model_validate(decided)
    assert response.match_id == market.match_a.match_id
    assert response.manager_decision == expected
    assert response.decided_at is not None
    assert decided.user_id == market.manager_a.user_id


def test_acceptance_creates_reservation_and_closes_competing_match(db, market):
    result = accept_match(db, market.manager_a.user_id, market.match_a.match_id)

    db.expire_all()
    assert result.manager_decision == models.ManagerDecision.ACCEPTED
    assert market.match_b.manager_decision == models.ManagerDecision.CLOSED
    assert (
        db.query(models.Reservation)
        .filter(models.Reservation.match_id == market.match_a.match_id)
        .count()
        == 1
    )


@pytest.mark.parametrize("decide", [accept_match, skip_match])
def test_decided_match_leaves_opportunities(db, market, decide):
    decide(db, market.manager_a.user_id, market.match_a.match_id)

    assert list_opportunities_for_fleet_manager(db, market.manager_a.user_id) == []


@pytest.mark.parametrize("decide", [accept_match, skip_match])
def test_decided_match_cannot_be_decided_again(db, market, decide):
    decide(db, market.manager_a.user_id, market.match_a.match_id)

    with pytest.raises(ShipmentNoLongerAvailableError):
        accept_match(db, market.manager_a.user_id, market.match_a.match_id)


@pytest.mark.parametrize("decide", [accept_match, skip_match])
def test_shipper_cannot_decide(db, market, decide):
    with pytest.raises(ActorNotAllowedError):
        decide(db, market.shipper_user.user_id, market.match_a.match_id)

    assert_still_pending(db, market.match_a)


@pytest.mark.parametrize("decide", [accept_match, skip_match])
def test_another_company_cannot_decide(db, market, decide):
    with pytest.raises(MatchAccessDeniedError):
        decide(db, market.manager_b.user_id, market.match_a.match_id)

    assert_still_pending(db, market.match_a)


@pytest.mark.parametrize("decide", [accept_match, skip_match])
def test_missing_match_cannot_be_decided(db, market, decide):
    with pytest.raises(MatchNotFoundError):
        decide(db, market.manager_a.user_id, uuid.uuid4())


@pytest.mark.parametrize(
    "make_stale",
    [
        lambda m: setattr(m.match_a, "manager_decision", models.ManagerDecision.CLOSED),
        lambda m: setattr(
            m.truck_a, "availability_status", models.AvailabilityStatus.UNAVAILABLE
        ),
        lambda m: setattr(m.truck_a, "body_type", models.BodyType.TANKER),
        lambda m: setattr(m.truck_a, "capacity_kg", 1_000),
        lambda m: setattr(m.shipment, "status", models.ShipmentStatus.CANCELLED),
    ],
)
def test_stale_match_cannot_be_accepted(db, market, make_stale):
    make_stale(market)
    db.commit()

    with pytest.raises(ShipmentNoLongerAvailableError) as error:
        accept_match(db, market.manager_a.user_id, market.match_a.match_id)

    assert str(error.value) == "This shipment is no longer available."
    db.expire_all()
    assert market.match_a.user_id is None
    assert market.match_a.decided_at is None


def test_reservation_failure_does_not_leave_acceptance_state(db, market, monkeypatch):
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        accept_match(db, market.manager_a.user_id, market.match_a.match_id)

    monkeypatch.setattr(db, "commit", original_commit)
    db.expire_all()

    assert market.match_a.manager_decision == models.ManagerDecision.PENDING
    assert market.match_b.manager_decision == models.ManagerDecision.PENDING
    assert db.query(models.Reservation).count() == 0
