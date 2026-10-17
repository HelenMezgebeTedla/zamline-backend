import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from models import Company, Reservation, Shipment, ShipmentMatch, Truck, User
from models.companies import CompanyType, VerificationStatus
from models.shipment_matches import MatchOutcome
from models.shipments import ShipmentStatus
from models.trucks import AvailabilityStatus, BodyType
from models.users import UserRole


def make_id(prefix: str, n: int):
    return uuid.UUID(f"{prefix}0000000-0000-4000-8000-{n:012d}")


SHIPPER_CO = make_id("c", 1)
FLEET_A_CO = make_id("c", 2)
FLEET_B_CO = make_id("c", 3)
FLEET_C_CO = make_id("c", 4)
KELVIN = make_id("a", 1)
WILLIAM = make_id("a", 2)
MWILA = make_id("a", 3)
CHANDA = make_id("a", 4)
INACTIVE = make_id("a", 5)
TRUCK_A1 = make_id("b", 1)
TRUCK_A2 = make_id("b", 2)
TRUCK_B1 = make_id("b", 3)
TRUCK_C1 = make_id("b", 4)
SHIP_1 = make_id("d", 1)
SHIP_2 = make_id("d", 2)
SHIP_3 = make_id("d", 3)
SHIP_4 = make_id("d", 4)
MATCH_A_S1 = make_id("e", 1)
MATCH_B_S1 = make_id("e", 2)
MATCH_C_S1 = make_id("e", 3)
MATCH_A_S2 = make_id("e", 4)
MATCH_B_S2 = make_id("e", 5)
MATCH_A2_S3 = make_id("e", 6)
MATCH_A_S4 = make_id("e", 7)

MOCK_COMPANIES = [SHIPPER_CO, FLEET_A_CO, FLEET_B_CO, FLEET_C_CO]
MOCK_USERS = [KELVIN, WILLIAM, MWILA, CHANDA, INACTIVE]
MOCK_TRUCKS = [TRUCK_A1, TRUCK_A2, TRUCK_B1, TRUCK_C1]
MOCK_SHIPMENTS = [SHIP_1, SHIP_2, SHIP_3, SHIP_4]
MOCK_MATCHES = [
    MATCH_A_S1,
    MATCH_B_S1,
    MATCH_C_S1,
    MATCH_A_S2,
    MATCH_B_S2,
    MATCH_A2_S3,
    MATCH_A_S4,
]

MOCK_PASSWORD_HASH = "mock-hash-not-a-real-password"


def get_user(db: Session, user_id: uuid.UUID):
    return db.query(User).filter(User.user_id == user_id).first()


def get_shipment(db: Session, shipment_id: uuid.UUID):
    return db.query(Shipment).filter(Shipment.shipment_id == shipment_id).first()


def get_match(db: Session, match_id: uuid.UUID):
    return db.query(ShipmentMatch).filter(ShipmentMatch.match_id == match_id).first()


LUSAKA = (Decimal("-15.416700"), Decimal("28.283300"))
NDOLA = (Decimal("-12.968300"), Decimal("28.636600"))
KITWE = (Decimal("-12.802400"), Decimal("28.213200"))
LIVINGSTONE = (Decimal("-17.841900"), Decimal("25.854300"))


def companies():
    now = datetime.now(UTC)
    fleet_costs = dict(
        fuel_price_per_litre=Decimal("31.50"),
        driver_daily_allowance=Decimal("450.00"),
        toll_assumption=Decimal("120.00"),
        other_costs=Decimal("300.00"),
    )
    return [
        Company(
            company_id=SHIPPER_CO,
            company_type=CompanyType.SHIPPER,
            business_name="Chipatala Grains Ltd",
            registration_number="MOCK-0001",
            company_email="logistics@chipatalagrains.co.zm",
            phone_number="+260977111222",
            verification_status=VerificationStatus.VERIFIED,
            verified_at=now,
        ),
        Company(
            company_id=FLEET_A_CO,
            company_type=CompanyType.FLEET,
            business_name="Phiri Haulage Ltd",
            registration_number="MOCK-0002",
            company_email="ops@phirihaulage.co.zm",
            phone_number="+260966333444",
            verification_status=VerificationStatus.VERIFIED,
            verified_at=now,
            **fleet_costs,
        ),
        Company(
            company_id=FLEET_B_CO,
            company_type=CompanyType.FLEET,
            business_name="Copperbelt Movers Ltd",
            registration_number="MOCK-0003",
            company_email="dispatch@cbmovers.co.zm",
            phone_number="+260955555666",
            verification_status=VerificationStatus.VERIFIED,
            verified_at=now,
            **fleet_costs,
        ),
        Company(
            company_id=FLEET_C_CO,
            company_type=CompanyType.FLEET,
            business_name="Kafue Road Transport",
            registration_number="MOCK-0004",
            company_email="info@kafueroad.co.zm",
            phone_number="+260977777888",
            verification_status=VerificationStatus.PENDING,
            **fleet_costs,
        ),
    ]


def users():
    def u(uid, co, first, last, email, role, active=True):
        return User(
            user_id=uid,
            company_id=co,
            first_name=first,
            last_name=last,
            email=email,
            password_hash=MOCK_PASSWORD_HASH,
            role=role,
            is_active=active,
        )

    return [
        u(
            KELVIN,
            SHIPPER_CO,
            "Kelvin",
            "Chipatala",
            "kelvin@chipatalagrains.co.zm",
            UserRole.SHIPPER,
        ),
        u(
            WILLIAM,
            FLEET_A_CO,
            "William",
            "Phiri",
            "william@phirihaulage.co.zm",
            UserRole.FLEET_MANAGER,
        ),
        u(
            MWILA,
            FLEET_B_CO,
            "Mwila",
            "Banda",
            "mwila@cbmovers.co.zm",
            UserRole.FLEET_MANAGER,
        ),
        u(
            CHANDA,
            FLEET_C_CO,
            "Chanda",
            "Zulu",
            "chanda@kafueroad.co.zm",
            UserRole.FLEET_MANAGER,
        ),
        u(
            INACTIVE,
            FLEET_A_CO,
            "Old",
            "Account",
            "old@phirihaulage.co.zm",
            UserRole.FLEET_MANAGER,
            active=False,
        ),
    ]


def trucks():
    def t(tid, co, plate, ttype, body, cap, avail=AvailabilityStatus.AVAILABLE):
        return Truck(
            truck_id=tid,
            company_id=co,
            plate_number=plate,
            truck_type=ttype,
            body_type=body,
            capacity_kg=cap,
            fuel_consumption_l_per_100km=38.0,
            maintenance_per_km=Decimal("2.40"),
            availability_status=avail,
            current_location="Lusaka",
        )

    return [
        t(
            TRUCK_A1,
            FLEET_A_CO,
            "MOCK BAZ 1234",
            "semi-trailer",
            BodyType.FLATBED,
            30000,
        ),
        t(
            TRUCK_A2,
            FLEET_A_CO,
            "MOCK BAZ 5678",
            "rigid",
            BodyType.BOX,
            10000,
            avail=AvailabilityStatus.UNAVAILABLE,
        ),
        t(
            TRUCK_B1,
            FLEET_B_CO,
            "MOCK BCD 4321",
            "semi-trailer",
            BodyType.FLATBED,
            32000,
        ),
        t(
            TRUCK_C1,
            FLEET_C_CO,
            "MOCK BKF 9876",
            "semi-trailer",
            BodyType.FLATBED,
            30000,
        ),
    ]


def shipments():
    soon = datetime.now(UTC) + timedelta(days=2)

    def s(sid, origin, o, dest, d, cargo, kg, body, amount, status=ShipmentStatus.OPEN):
        return Shipment(
            shipment_id=sid,
            company_id=SHIPPER_CO,
            user_id=KELVIN,
            origin_address=origin,
            origin_latitude=o[0],
            origin_longitude=o[1],
            destination_address=dest,
            destination_latitude=d[0],
            destination_longitude=d[1],
            cargo_type=cargo,
            weight_kg=kg,
            required_body_type=body,
            pickup_time=soon,
            proposed_amount=Decimal(amount),
            status=status,
        )

    return [
        s(
            SHIP_1,
            "Lusaka, Zambia",
            LUSAKA,
            "Ndola, Zambia",
            NDOLA,
            "maize",
            25000,
            BodyType.FLATBED,
            "18500.00",
        ),
        s(
            SHIP_2,
            "Kitwe, Zambia",
            KITWE,
            "Lusaka, Zambia",
            LUSAKA,
            "copper cathode",
            28000,
            BodyType.FLATBED,
            "21000.00",
        ),
        s(
            SHIP_3,
            "Lusaka, Zambia",
            LUSAKA,
            "Livingstone, Zambia",
            LIVINGSTONE,
            "boxed goods",
            8000,
            BodyType.BOX,
            "16000.00",
        ),
        s(
            SHIP_4,
            "Ndola, Zambia",
            NDOLA,
            "Lusaka, Zambia",
            LUSAKA,
            "fertiliser",
            20000,
            BodyType.FLATBED,
            "17000.00",
            status=ShipmentStatus.EXPIRED,
        ),
    ]


def matches():
    def m(mid, sid, tid, dist, mins, total, proposed):
        total, proposed = Decimal(total), Decimal(proposed)
        margin = proposed - total
        outcome = (
            MatchOutcome.PROFIT
            if margin > 0
            else MatchOutcome.LOSS
            if margin < 0
            else MatchOutcome.BREAK_EVEN
        )
        return ShipmentMatch(
            match_id=mid,
            shipment_id=sid,
            truck_id=tid,
            distance_km=dist,
            duration=mins,
            estimated_total_cost=total,
            proposed_amount=proposed,
            estimated_margin=margin,
            outcome=outcome,
            ai_explanation="Mock estimate: fuel is the main cost driver.",
        )

    return [
        m(MATCH_A_S1, SHIP_1, TRUCK_A1, 320.0, 300, "14200.00", "18500.00"),
        m(MATCH_B_S1, SHIP_1, TRUCK_B1, 320.0, 300, "14650.00", "18500.00"),
        m(MATCH_C_S1, SHIP_1, TRUCK_C1, 320.0, 300, "14400.00", "18500.00"),
        m(MATCH_A_S2, SHIP_2, TRUCK_A1, 360.0, 330, "16100.00", "21000.00"),
        m(MATCH_B_S2, SHIP_2, TRUCK_B1, 360.0, 330, "15900.00", "21000.00"),
        m(MATCH_A2_S3, SHIP_3, TRUCK_A2, 480.0, 420, "15200.00", "16000.00"),
        m(MATCH_A_S4, SHIP_4, TRUCK_A1, 320.0, 300, "14000.00", "17000.00"),
    ]


def insert_mock_rows(db: Session):
    for group in (companies(), users(), trucks(), shipments(), matches()):
        db.add_all(group)
        db.commit()


def reset_all(db: Session):
    for model in (Reservation, ShipmentMatch, Shipment, Truck, User, Company):
        db.query(model).delete(synchronize_session=False)
    insert_mock_rows(db)
