import os
import threading
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Company, Reservation, ShipmentMatch, Truck, User
from models.companies import CompanyType, VerificationStatus
from models.reservations import ReservationStatus
from models.trucks import BodyType
from models.users import UserRole
from services.reservations import (
    LOAD_ALREADY_CLAIMED,
    NO_LONGER_OPEN,
    accept_match,
    cancel_reservation,
    get_contact,
    get_reservation,
    list_reservations,
)
from tests import reservation_data as d


@pytest.fixture(autouse=True)
def reservation_rows(request):
    if "pg_session_factory" in request.fixturenames:
        return
    d.insert_mock_rows(request.getfixturevalue("db_session"))


def as_user(db, user_id) -> User:
    return d.get_user(db, user_id)


def accept(db, user_id=d.WILLIAM, match_id=d.MATCH_A_S1) -> Reservation:
    return accept_match(db, as_user(db, user_id), match_id)


def rejected(call, status_code: int) -> str:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status_code
    return caught.value.detail


def test_fleet_manager_can_accept_open_shipment(db_session):
    reservation = accept(db_session)

    assert reservation.shipment_id == d.SHIP_1
    assert reservation.company_id == d.FLEET_A_CO
    assert reservation.truck_id == d.TRUCK_A1
    assert reservation.user_id == d.WILLIAM
    assert reservation.match_id == d.MATCH_A_S1
    assert reservation.status == ReservationStatus.ACCEPTED


def test_accept_locks_shipment_and_closes_competing_matches(db_session):
    accept(db_session)

    assert d.get_shipment(db_session, d.SHIP_1).status == "confirmed"
    winner = d.get_match(db_session, d.MATCH_A_S1)
    assert winner.manager_decision == "accepted"
    assert winner.user_id == d.WILLIAM
    assert winner.decided_at is not None
    assert d.get_match(db_session, d.MATCH_B_S1).manager_decision == "closed"
    assert d.get_match(db_session, d.MATCH_C_S1).manager_decision == "closed"
    assert d.get_match(db_session, d.MATCH_A_S2).manager_decision == "pending"


def test_second_company_gets_load_already_claimed(db_session):
    accept(db_session)

    detail = rejected(lambda: accept(db_session, d.MWILA, d.MATCH_B_S1), 409)

    assert detail == LOAD_ALREADY_CLAIMED
    assert db_session.query(Reservation).count() == 1


def test_accepting_same_match_twice_is_rejected(db_session):
    accept(db_session)
    assert "already accepted" in rejected(lambda: accept(db_session), 409)


def test_cannot_accept_expired_shipment(db_session):
    detail = rejected(lambda: accept(db_session, match_id=d.MATCH_A_S4), 409)
    assert detail == NO_LONGER_OPEN


def test_cannot_accept_with_unavailable_truck(db_session):
    detail = rejected(lambda: accept(db_session, match_id=d.MATCH_A2_S3), 409)
    assert detail == "This truck is not available"


def test_shipper_cannot_accept(db_session):
    rejected(lambda: accept(db_session, d.KELVIN, d.MATCH_A_S1), 403)


def test_unverified_company_cannot_accept(db_session):
    detail = rejected(lambda: accept(db_session, d.CHANDA, d.MATCH_C_S1), 403)
    assert "not verified" in detail


def test_cannot_accept_another_companys_match(db_session):
    rejected(lambda: accept(db_session, d.MWILA, d.MATCH_A_S1), 404)


def test_unknown_match_returns_404(db_session):
    rejected(lambda: accept(db_session, match_id=uuid.uuid4()), 404)


def test_each_party_sees_only_their_reservations(db_session):
    accept(db_session)
    accept(db_session, d.MWILA, d.MATCH_B_S2)

    william = list_reservations(db_session, as_user(db_session, d.WILLIAM))
    mwila = list_reservations(db_session, as_user(db_session, d.MWILA))
    kelvin = list_reservations(db_session, as_user(db_session, d.KELVIN))

    assert [r.shipment_id for r in william] == [d.SHIP_1]
    assert [r.shipment_id for r in mwila] == [d.SHIP_2]
    assert {r.shipment_id for r in kelvin} == {d.SHIP_1, d.SHIP_2}


def test_other_company_cannot_read_reservation(db_session):
    reservation_id = accept(db_session).reservation_id

    for user_id in (d.WILLIAM, d.KELVIN):
        found = get_reservation(
            db_session, as_user(db_session, user_id), reservation_id
        )
        assert found.reservation_id == reservation_id
    rejected(
        lambda: get_reservation(
            db_session, as_user(db_session, d.MWILA), reservation_id
        ),
        404,
    )


def test_status_filter(db_session):
    reservation_id = accept(db_session).reservation_id
    william = as_user(db_session, d.WILLIAM)
    cancel_reservation(db_session, william, reservation_id)

    assert list_reservations(db_session, william, ReservationStatus.ACCEPTED) == []
    cancelled = list_reservations(db_session, william, ReservationStatus.CANCELLED)
    assert [r.reservation_id for r in cancelled] == [reservation_id]


def test_cancel_reservation(db_session):
    reservation_id = accept(db_session).reservation_id

    cancelled = cancel_reservation(
        db_session, as_user(db_session, d.WILLIAM), reservation_id, "Truck broke down"
    )

    assert cancelled.status == ReservationStatus.CANCELLED
    assert d.get_shipment(db_session, d.SHIP_1).status == "cancelled"


def test_cannot_cancel_twice(db_session):
    reservation_id = accept(db_session).reservation_id
    william = as_user(db_session, d.WILLIAM)
    cancel_reservation(db_session, william, reservation_id)

    detail = rejected(
        lambda: cancel_reservation(db_session, william, reservation_id), 409
    )
    assert detail == "Reservation is already cancelled"


def test_outsider_cannot_cancel(db_session):
    reservation_id = accept(db_session).reservation_id
    rejected(
        lambda: cancel_reservation(
            db_session, as_user(db_session, d.MWILA), reservation_id
        ),
        404,
    )


def test_database_blocks_a_second_reservation_even_without_the_service(db_session):
    for match, truck, co, user in (
        (d.MATCH_A_S1, d.TRUCK_A1, d.FLEET_A_CO, d.WILLIAM),
        (d.MATCH_B_S1, d.TRUCK_B1, d.FLEET_B_CO, d.MWILA),
    ):
        db_session.add(
            Reservation(
                shipment_id=d.SHIP_1,
                company_id=co,
                truck_id=truck,
                user_id=user,
                match_id=match,
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def contact(db, user_id, shipment_id=d.SHIP_1):
    return get_contact(db, as_user(db, user_id), shipment_id)


def assert_masked(result):
    assert result.visible is False
    assert result.counterparty_role is None
    assert result.business_name is None
    assert result.company_email is None
    assert result.phone_number is None


def test_contacts_masked_while_shipment_is_open(db_session):
    for user_id in (d.KELVIN, d.WILLIAM, d.MWILA):
        assert_masked(contact(db_session, user_id))


def test_shipper_sees_fleet_contact_after_acceptance(db_session):
    accept(db_session)
    result = contact(db_session, d.KELVIN)

    assert result.visible is True
    assert result.counterparty_role == "fleet"
    assert result.business_name == "Phiri Haulage Ltd"
    assert result.phone_number == "+260966333444"
    assert result.company_email == "ops@phirihaulage.co.zm"


def test_winning_fleet_sees_shipper_contact(db_session):
    accept(db_session)
    result = contact(db_session, d.WILLIAM)

    assert result.visible is True
    assert result.counterparty_role == "shipper"
    assert result.business_name == "Chipatala Grains Ltd"


def test_losing_fleet_still_sees_nothing(db_session):
    accept(db_session)
    assert_masked(contact(db_session, d.MWILA))


def test_unrelated_fleet_cannot_see_shipment(db_session):
    rejected(lambda: contact(db_session, d.MWILA, d.SHIP_3), 404)


def test_unknown_shipment_404(db_session):
    rejected(lambda: contact(db_session, d.KELVIN, uuid.uuid4()), 404)


def test_unverified_company_cannot_view_contacts(db_session):
    rejected(lambda: contact(db_session, d.CHANDA), 403)


def test_contacts_hidden_again_after_cancellation(db_session):
    reservation_id = accept(db_session).reservation_id
    cancel_reservation(db_session, as_user(db_session, d.WILLIAM), reservation_id)
    assert_masked(contact(db_session, d.KELVIN))


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgres"),
    reason="Set TEST_DATABASE_URL to a Postgres database ending in _test",
)
N_COMPANIES = 10


@pytest.fixture
def pg_session_factory():
    url = make_url(TEST_DATABASE_URL)
    if not (url.database or "").endswith("_test"):
        pytest.fail(f"Refusing to run: database '{url.database}' does not end in _test")
    if url.drivername in ("postgres", "postgresql", "postgresql+psycopg"):
        url = url.set(drivername="postgresql+psycopg2")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        d.reset_all(db)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _add_competing_fleets(factory, n: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    pairs = []
    with factory() as db:
        for i in range(n):
            co, user, truck, match = (uuid.uuid4() for _ in range(4))
            db.add(
                Company(
                    company_id=co,
                    company_type=CompanyType.FLEET,
                    business_name=f"Race Fleet {i}",
                    registration_number=f"RACE{i:08d}",
                    company_email=f"race{i}@fleet.zm",
                    phone_number="+260970000000",
                    verification_status=VerificationStatus.VERIFIED,
                )
            )
            db.flush()
            db.add(
                User(
                    user_id=user,
                    company_id=co,
                    first_name="Race",
                    last_name=str(i),
                    email=f"mgr{i}@fleet.zm",
                    password_hash="x",
                    role=UserRole.FLEET_MANAGER,
                )
            )
            db.add(
                Truck(
                    truck_id=truck,
                    company_id=co,
                    plate_number=f"RACE {i}",
                    truck_type="semi-trailer",
                    body_type=BodyType.FLATBED,
                    capacity_kg=30000,
                    fuel_consumption_l_per_100km=38,
                    maintenance_per_km=Decimal("2.40"),
                )
            )
            db.flush()
            db.add(ShipmentMatch(match_id=match, shipment_id=d.SHIP_1, truck_id=truck))
            pairs.append((user, match))
        db.commit()
    return pairs


def _race(factory, pairs) -> list[str]:
    barrier = threading.Barrier(len(pairs))
    results: list[str] = []
    lock = threading.Lock()

    def attempt(user_id, match_id):
        with factory() as db:
            user = d.get_user(db, user_id)
            barrier.wait()
            try:
                accept_match(db, user, match_id)
                outcome = "won"
            except HTTPException as exc:
                outcome = exc.detail
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=p) for p in pairs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


@needs_postgres
@pytest.mark.parametrize("round_no", range(5))
def test_only_one_of_many_simultaneous_acceptances_wins(pg_session_factory, round_no):
    pairs = _add_competing_fleets(pg_session_factory, N_COMPANIES)

    results = _race(pg_session_factory, pairs)

    assert len(results) == N_COMPANIES
    assert results.count("won") == 1, results
    assert results.count(LOAD_ALREADY_CLAIMED) == N_COMPANIES - 1, results

    with pg_session_factory() as db:
        reservations = (
            db.query(Reservation).filter(Reservation.shipment_id == d.SHIP_1).all()
        )
        assert len(reservations) == 1
        assert d.get_shipment(db, d.SHIP_1).status == "confirmed"
        decisions = [
            match.manager_decision
            for match in db.query(ShipmentMatch)
            .filter(ShipmentMatch.shipment_id == d.SHIP_1)
            .all()
        ]
        assert decisions.count("accepted") == 1
        assert "pending" not in decisions
