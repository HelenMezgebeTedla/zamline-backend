from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from services.gemini import GeminiStructuredResult
from services.routing import RouteSummary
from database import Base

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
    company = create_company(db, suffix, company_type=models.CompanyType.SHIPPER)
    user = create_user(db, company, suffix, role=models.UserRole.SHIPPER)
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


STUB_ROUTE = RouteSummary(distance_km=320.0, duration_minutes=270)

STUB_AI_ASSESSMENT = {
    "estimated_total_cost": 4540.00,
    "summary": "Copperbelt journey with one supported extra driver-day cost.",
    "major_cost_factors": [
        {
            "factor": "Border and customs delays",
            "status": "not_applicable",
            "amount": None,
            "reason": "The test journey does not require a border crossing.",
            "calculation_basis": None,
            "citations": [],
        },
        {
            "factor": "Road condition and corridor congestion",
            "status": "quantified",
            "amount": 450.00,
            "reason": "Retrieved test evidence supports one extra driver day.",
            "calculation_basis": {
                "quantity": 1,
                "unit": "day",
                "rate_source": "configured_driver_rate",
                "evidence_text": "the delay may add 1 day to the journey",
            },
            "citations": ["[DOC018, p. 20]"],
        },
        {
            "factor": "Cargo security and insurance",
            "status": "not_quantified",
            "amount": None,
            "reason": "The risk cannot be priced from the available evidence.",
            "calculation_basis": None,
            "citations": [],
        },
    ],
    "assumptions": ["Current company settings remain valid."],
    "risk_factors": ["Some journey risks are not quantified."],
    "limitations": ["Only validated monetary costs are added."],
    "evidence_citations": [
        {
            "citation": "[DOC018, p. 20]",
            "supports": "One additional driver day",
        }
    ],
    "_grounding_evidence": {
        "[DOC018, p. 20]": ["the delay may add 1 day to the journey"]
    },
}


STUB_REFERENCE_FILES = [
    {"uri": "https://example.test/files/reference-01", "mime_type": "text/plain"}
]


def stub_assessment_services(monkeypatch, ai_response=None, route=STUB_ROUTE):
    monkeypatch.setattr(
        "services.match_assessments.GEMINI_FILE_SEARCH_STORE",
        "fileSearchStores/test-store",
    )
    calls = []

    def fake_route(shipment):
        return route

    def fake_gemini(
        instructions,
        context,
        response_schema,
        *args,
        **kwargs,
    ):
        calls.append(context)

        payload = STUB_AI_ASSESSMENT if ai_response is None else ai_response

        if not isinstance(payload, dict):
            return payload

        grounding = payload.get("_grounding_evidence", {})
        data = {
            key: value for key, value in payload.items() if key != "_grounding_evidence"
        }

        contexts = []
        source_ids = set()

        if isinstance(grounding, dict):
            for citation, passages in grounding.items():
                if not isinstance(passages, (list, tuple)):
                    continue

                body = str(citation).strip("[]")

                if ", p. " in body:
                    source_id, page = body.split(", p. ", 1)
                    try:
                        page_number = int(page)
                    except ValueError:
                        page_number = None
                else:
                    source_id = body
                    page_number = None

                source_ids.add(source_id)

                for passage in passages:
                    contexts.append(
                        {
                            "text": str(passage),
                            "page_number": page_number,
                            "metadata": {
                                "source_ids": [source_id],
                            },
                        }
                    )

        return GeminiStructuredResult(
            data=data,
            grounded_source_ids=frozenset(source_ids),
            grounding_contexts=tuple(contexts),
        )

    monkeypatch.setattr(
        "services.shipment_matches.get_route_summary",
        fake_route,
    )
    monkeypatch.setattr(
        "services.match_assessments.generate_structured_json",
        fake_gemini,
    )
    return calls
