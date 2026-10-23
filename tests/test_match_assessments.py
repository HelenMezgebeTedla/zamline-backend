import importlib.util
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from google.genai import errors

import pytest

import models
import services.gemini as gemini
import services.match_assessments as match_assessments
import services.routing as routing
from fleet_helpers import (
    STUB_AI_ASSESSMENT,
    create_fleet_manager,
    create_shipment,
    create_shipper,
    create_test_engine,
    create_test_sessionmaker,
    create_truck,
    stub_assessment_services,
)
from schemas.shipment_matches import MatchDetailResponse
from services.gemini import GeminiRequestRejectedError, GeminiUnavailableError
from services.match_assessments import (
    ASSESSMENT_RESPONSE_SCHEMA,
    assessment_status,
    calculate_margin,
)
from services.operating_costs import (
    CostSettingsIncompleteError,
    calculate_operating_costs,
    count_driver_days,
)
from services.routing import (
    GeocodedPlace,
    RouteSummary,
    parse_geocoded_places,
    parse_route_summary,
)
from services.shipment_matches import (
    assess_match,
    generate_matches_for_fleet_manager,
    get_match_detail,
    start_assessment_with_run_id,
    finish_assessment,
)


@pytest.fixture
def db():
    engine = create_test_engine()
    session = create_test_sessionmaker(engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def pending_match(db):
    fleet, manager = create_fleet_manager(db, "FA")
    truck = create_truck(db, fleet, "FA")
    shipper, shipper_user = create_shipper(db, "SH")
    create_shipment(db, shipper, shipper_user, "SH")
    match = generate_matches_for_fleet_manager(db, manager.user_id)[0]
    return fleet, manager, truck, match


def assess_with(db, pending_match, monkeypatch, ai_response):
    stub_assessment_services(monkeypatch, ai_response=ai_response)
    fleet, manager, truck, match = pending_match
    detail = assess_match(db, manager.user_id, match.match_id)
    return match, MatchDetailResponse.model_validate(detail)


def test_operating_costs_use_litres_per_100km(db, pending_match):
    fleet, manager, truck, match = pending_match

    costs = calculate_operating_costs(
        fleet, truck, RouteSummary(distance_km=320.0, duration_minutes=270)
    )

    assert costs.fuel_litres == Decimal("96.00")
    assert costs.fuel_cost == Decimal("2640.00")
    assert costs.driver_days == 1
    assert costs.driver_cost == Decimal("450.00")
    assert costs.maintenance_cost == Decimal("800.00")
    assert costs.toll_cost == Decimal("120.00")
    assert costs.other_cost == Decimal("80.00")
    assert costs.baseline_total == Decimal("4090.00")


@pytest.mark.parametrize(
    "minutes, days", [(0, 1), (540, 1), (541, 2), (1080, 2), (1081, 3)]
)
def test_driver_days_follow_daily_driving_limit(minutes, days):
    assert count_driver_days(minutes) == days


def test_missing_cost_settings_are_rejected(db, pending_match):
    fleet, manager, truck, match = pending_match
    fleet.fuel_price_per_litre = None

    with pytest.raises(CostSettingsIncompleteError, match="fuel_price_per_litre"):
        calculate_operating_costs(fleet, truck, RouteSummary(100.0, 60))


def test_backend_calculates_margin_from_estimated_total_cost():
    margin = calculate_margin(Decimal("18500.00"), Decimal("4540.00"))

    assert margin.estimated_margin == Decimal("13960.00")
    assert margin.margin_percentage == Decimal("75.46")
    assert margin.outcome == models.MatchOutcome.PROFIT


@pytest.mark.parametrize(
    "payment, outcome",
    [
        (Decimal("1000.01"), models.MatchOutcome.PROFIT),
        (Decimal("1000.00"), models.MatchOutcome.BREAK_EVEN),
        (Decimal("900.00"), models.MatchOutcome.LOSS),
    ],
)
def test_margin_outcome(payment, outcome):
    assert calculate_margin(payment, Decimal("1000.00")).outcome == outcome


def test_parse_route_summary_converts_units():
    payload = {
        "features": [
            {"properties": {"summary": {"distance": 320500, "duration": 16260}}}
        ]
    }

    assert parse_route_summary(payload) == RouteSummary(320.5, 271)


def test_parse_geocoded_places_reads_label_and_coordinates():
    payload = {
        "features": [
            {
                "geometry": {"coordinates": [28.2833, -15.4167]},
                "properties": {"label": "Lusaka, Zambia"},
            }
        ]
    }

    assert parse_geocoded_places(payload) == [
        GeocodedPlace(label="Lusaka, Zambia", latitude=-15.4167, longitude=28.2833)
    ]


def test_ors_route_uses_driving_hgv_profile():
    url = routing.build_coordinates_directions_url(-12.8, 28.2, -15.4, 28.3)

    assert "/driving-hgv?" in url
    assert "start=28.2%2C-12.8" in url
    assert "end=28.3%2C-15.4" in url


def test_route_summary_routes_between_shipment_coordinates(monkeypatch):
    shipment = models.Shipment(
        origin_address="Kitwe",
        origin_latitude=-12.8,
        origin_longitude=28.2,
        destination_address="Lusaka",
        destination_latitude=-15.4,
        destination_longitude=28.3,
    )
    routed = []

    def fake_route(*coordinates):
        routed.append(coordinates)
        return RouteSummary(385.0, 315)

    def unexpected_geocode(text, size):
        raise AssertionError("geocoding is not needed")

    monkeypatch.setattr(routing, "get_route_between_coordinates", fake_route)
    monkeypatch.setattr(routing, "geocode_address", unexpected_geocode)

    assert routing.get_route_summary(shipment) == RouteSummary(385.0, 315)
    assert routed == [(-12.8, 28.2, -15.4, 28.3)]


def test_route_geocodes_shipments_without_coordinates(monkeypatch):
    shipment = models.Shipment(origin_address="Kitwe", destination_address="Lusaka")
    searched = []

    def fake_geocode(text, size):
        searched.append(text)
        if text.startswith("Kitwe"):
            return [GeocodedPlace(label="Kitwe", latitude=-12.8, longitude=28.2)]
        return [GeocodedPlace(label="Lusaka", latitude=-15.4, longitude=28.3)]

    monkeypatch.setattr(routing, "geocode_address", fake_geocode)

    assert routing.shipment_coordinates(shipment) == (-12.8, 28.2, -15.4, 28.3)
    assert searched == ["Kitwe, Zambia", "Lusaka, Zambia"]


def test_route_reports_unknown_addresses(monkeypatch):
    shipment = models.Shipment(origin_address="Nowhere", destination_address="Lusaka")
    monkeypatch.setattr(routing, "geocode_address", lambda text, size: [])

    with pytest.raises(routing.RouteUnavailableError):
        routing.shipment_coordinates(shipment)


def test_valid_ai_estimate_is_persisted_with_backend_margin(
    db, pending_match, monkeypatch
):
    match, response = assess_with(db, pending_match, monkeypatch, None)

    db.expire_all()
    assert match.distance_km == 320.0
    assert match.estimated_total_cost == Decimal("4540.00")
    assert match.estimated_margin == Decimal("13960.00")
    assert match.outcome == models.MatchOutcome.PROFIT
    assert response.assessment_status == "completed"
    assert response.operating_cost_total == Decimal("4090.00")
    assert response.estimated_total_cost == Decimal("4540.00")
    assert response.estimated_margin == Decimal("13960.00")
    assert response.margin_percentage == Decimal("75.46")
    assert response.assessment.summary.startswith("Copperbelt")
    assert response.assessment.major_cost_factors[1].amount == Decimal("450.00")


def test_estimated_total_cost_comes_from_validated_quantified_cost(
    db, pending_match, monkeypatch
):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "estimated_total_cost": 4990.00,
        "major_cost_factors": [
            {
                **STUB_AI_ASSESSMENT["major_cost_factors"][1],
                "amount": 900.00,
                "calculation_basis": {
                    "quantity": 2,
                    "unit": "day",
                    "rate_source": "configured_driver_rate",
                    "evidence_text": "the delay may add 2 days to the journey",
                },
            }
        ],
        "_grounding_evidence": {
            "[DOC018, p. 20]": ["the delay may add 2 days to the journey"]
        },
    }

    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    assert response.estimated_total_cost == Decimal("4990.00")
    assert response.estimated_margin == Decimal("13510.00")


def test_loss_is_reported_when_validated_estimate_exceeds_payment(
    db, pending_match, monkeypatch
):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "estimated_total_cost": 19390.00,
        "major_cost_factors": [
            {
                **STUB_AI_ASSESSMENT["major_cost_factors"][1],
                "amount": 15300.00,
                "calculation_basis": {
                    "quantity": 34,
                    "unit": "day",
                    "rate_source": "configured_driver_rate",
                    "evidence_text": "the delay may add 34 days to the journey",
                },
            }
        ],
        "_grounding_evidence": {
            "[DOC018, p. 20]": ["the delay may add 34 days to the journey"]
        },
    }

    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    assert response.estimated_margin == Decimal("-890.00")
    assert response.outcome == models.MatchOutcome.LOSS


@pytest.mark.parametrize(
    "ai_response",
    [
        {**STUB_AI_ASSESSMENT, "estimated_total_cost": -1},
        {**STUB_AI_ASSESSMENT, "estimated_total_cost": "about five thousand"},
        {**STUB_AI_ASSESSMENT, "estimated_total_cost": None},
        {
            key: value
            for key, value in STUB_AI_ASSESSMENT.items()
            if key != "estimated_total_cost"
        },
        {**STUB_AI_ASSESSMENT, "summary": ""},
        {"unexpected": "shape"},
        ["not", "an", "object"],
    ],
)
def test_invalid_ai_output_fails_without_an_estimate(
    db, pending_match, monkeypatch, ai_response
):
    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    db.expire_all()
    assert response.assessment_status == "failed"
    assert response.assessment is None
    assert response.assessment_error
    assert response.estimated_total_cost is None
    assert response.estimated_margin is None
    assert response.outcome is None
    assert match.estimated_total_cost is None
    assert match.estimated_margin is None
    assert response.cost_breakdown is not None


def test_all_gemini_models_failing_does_not_fabricate_a_cost(
    db, pending_match, monkeypatch
):
    stub_assessment_services(monkeypatch)

    def failing_gemini(
        instructions,
        context,
        response_schema,
        file_search_store=None,
    ):
        raise GeminiUnavailableError("Gemini is busy, try again shortly")

    monkeypatch.setattr(
        "services.match_assessments.generate_structured_json",
        failing_gemini,
    )

    fleet, manager, truck, match = pending_match

    response = MatchDetailResponse.model_validate(
        assess_match(db, manager.user_id, match.match_id)
    )

    assert response.assessment_status == "failed"
    assert response.assessment_error == "Gemini is busy, try again shortly"
    assert response.estimated_total_cost is None
    assert response.outcome is None
    assert match.estimated_total_cost is None


def test_missing_file_search_store_fails_without_an_estimate(
    db, pending_match, monkeypatch
):
    stub_assessment_services(monkeypatch)
    monkeypatch.setattr(
        match_assessments,
        "GEMINI_FILE_SEARCH_STORE",
        "",
    )

    fleet, manager, truck, match = pending_match

    detail = assess_match(db, manager.user_id, match.match_id)

    assert detail["assessment_status"] == "failed"
    assert "File Search store" in detail["assessment_error"]
    assert detail["estimated_total_cost"] is None


def test_journey_context_is_sent_with_file_search_store(db, pending_match, monkeypatch):
    stub_assessment_services(monkeypatch)

    original = match_assessments.generate_structured_json
    received = []

    def capture(
        instructions,
        context,
        response_schema,
        file_search_store=None,
    ):
        received.append((context, file_search_store))
        return original(
            instructions,
            context,
            response_schema,
            file_search_store=file_search_store,
        )

    monkeypatch.setattr(
        "services.match_assessments.generate_structured_json",
        capture,
    )

    fleet, manager, truck, match = pending_match
    assess_match(db, manager.user_id, match.match_id)

    context, store = received[0]

    assert store
    assert store.startswith("fileSearchStores/")

    assert context["route"] == {
        "provider": "OpenRouteService",
        "profile": "driving-hgv",
        "distance_km": 320.0,
        "duration_minutes": 270,
    }

    assert context["shipment"]["proposed_payment"] == Decimal("18500.00")
    assert context["company_cost_settings"]["fuel_price_per_litre"] is not None
    assert context["calculated_operating_costs"]["operating_cost_total"] == Decimal(
        "4090.00"
    )

    text = json.dumps(context, default=str)

    for private in (
        "company_email",
        "phone_number",
        "password",
        "email",
        "pacra",
    ):
        assert private not in text.lower()


def test_old_retrieval_is_not_part_of_the_active_assessment(
    db, pending_match, monkeypatch
):
    calls = stub_assessment_services(monkeypatch)
    fleet, manager, truck, match = pending_match

    assess_match(db, manager.user_id, match.match_id)

    assert importlib.util.find_spec("services.document_evidence") is None
    assert importlib.util.find_spec("services.freight_evidence") is None
    assert importlib.util.find_spec("services.reference_context") is None
    assert not hasattr(match_assessments, "find_document_evidence")
    assert set(calls[0]) == {
        "shipment",
        "truck",
        "route",
        "company_cost_settings",
        "calculated_operating_costs",
    }


def test_unknown_reference_citations_are_rejected(db, pending_match, monkeypatch):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "evidence_citations": [
            {
                "citation": "[DOC018, p. 20]",
                "supports": "Nakonde clearance",
            },
            {
                "citation": "[DOC999, p. 1]",
                "supports": "Invented source",
            },
        ],
        "major_cost_factors": [
            STUB_AI_ASSESSMENT["major_cost_factors"][0],
            {
                **STUB_AI_ASSESSMENT["major_cost_factors"][1],
                "citations": [
                    "[DOC018, p. 20]",
                    "[DOC999, p. 1]",
                ],
            },
        ],
    }

    match, response = assess_with(
        db,
        pending_match,
        monkeypatch,
        ai_response,
    )

    assert response.assessment_status == "failed"
    assert response.assessment is None
    assert response.estimated_total_cost is None
    assert response.assessment_error


def test_rejected_file_search_request_fails_without_an_estimate(
    db, pending_match, monkeypatch
):
    stub_assessment_services(monkeypatch)

    def reject(
        instructions,
        context,
        response_schema,
        file_search_store=None,
    ):
        raise GeminiRequestRejectedError("Gemini assessment failed")

    monkeypatch.setattr(
        "services.match_assessments.generate_structured_json",
        reject,
    )

    fleet, manager, truck, match = pending_match
    detail = assess_match(db, manager.user_id, match.match_id)

    assert detail["assessment_status"] == "failed"
    assert detail["assessment_error"] == "Gemini assessment failed"
    assert detail["estimated_total_cost"] is None


def test_gemini_output_cannot_change_the_manager_decision(
    db, pending_match, monkeypatch
):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "manager_decision": "accepted",
        "decision": "accept",
    }

    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    db.expire_all()
    assert match.manager_decision == models.ManagerDecision.PENDING
    assert match.user_id is None
    assert match.decided_at is None
    assert response.manager_decision == models.ManagerDecision.PENDING
    assert "manager_decision" not in response.assessment.model_dump()


def test_stored_detail_returns_the_completed_assessment(db, pending_match, monkeypatch):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "evidence_citations": [
            {"citation": "[DOC018, p. 20]", "supports": "Nakonde clearance"}
        ],
    }
    stub_assessment_services(monkeypatch, ai_response=ai_response)
    fleet, manager, truck, match = pending_match
    assess_match(db, manager.user_id, match.match_id)

    db.expire_all()
    response = MatchDetailResponse.model_validate(
        get_match_detail(db, manager.user_id, match.match_id)
    )

    assert response.assessment_status == "completed"
    assert response.estimated_total_cost == Decimal("4540.00")
    assert response.reference_sources[0].citation == "[DOC018, p. 20]"


def test_stale_running_assessment_is_reported_as_failed():
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()

    assert assessment_status(
        {"assessment_status": "running", "assessment_updated_at": recent}
    ) == ("running", None)
    assert assessment_status(
        {"assessment_status": "running", "assessment_updated_at": old}
    ) == ("failed", "The assessment was interrupted, run it again")


def configure_gemini(monkeypatch, fallbacks):
    monkeypatch.setattr(gemini, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(gemini, "GEMINI_MODEL", "primary")
    monkeypatch.setattr(gemini, "GEMINI_FALLBACK_MODELS", fallbacks)
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)


def test_gemini_retries_then_falls_back_when_primary_model_is_busy(monkeypatch):
    configure_gemini(monkeypatch, ["primary", "backup"])
    tried = []

    def fake_call(
        client,
        model,
        instructions,
        context,
        response_schema,
        store,
    ):
        tried.append(model)
        if model == "primary":
            raise errors.ServerError(
                503,
                {
                    "error": {
                        "code": 503,
                        "message": "busy",
                        "status": "UNAVAILABLE",
                    }
                },
            )
        return {"ok": True}

    monkeypatch.setattr(gemini, "call_model", fake_call)

    assert gemini.generate_structured_json(
        "i",
        {},
        {},
        file_search_store="fileSearchStores/test-store",
    ) == {"ok": True}
    assert tried == ["primary", "primary", "backup"]


def test_gemini_moves_to_fallback_after_a_timeout(monkeypatch):
    configure_gemini(monkeypatch, ["backup"])
    tried = []

    def fake_call(
        client,
        model,
        instructions,
        context,
        response_schema,
        store,
    ):
        tried.append(model)
        if model == "primary":
            raise TimeoutError
        return {"ok": True}

    monkeypatch.setattr(gemini, "call_model", fake_call)

    assert gemini.generate_structured_json(
        "i",
        {},
        {},
        file_search_store="fileSearchStores/test-store",
    ) == {"ok": True}
    assert tried == ["primary", "primary", "backup"]


def test_gemini_reports_busy_when_every_model_fails(monkeypatch):
    configure_gemini(monkeypatch, ["backup"])

    def fake_call(
        client,
        model,
        instructions,
        context,
        response_schema,
        store,
    ):
        raise errors.ServerError(
            503,
            {
                "error": {
                    "code": 503,
                    "message": "busy",
                    "status": "UNAVAILABLE",
                }
            },
        )

    monkeypatch.setattr(gemini, "call_model", fake_call)

    with pytest.raises(GeminiUnavailableError, match="busy"):
        gemini.generate_structured_json(
            "i",
            {},
            {},
            file_search_store="fileSearchStores/test-store",
        )


def test_gemini_rejects_invalid_requests_without_fallback(monkeypatch):
    configure_gemini(monkeypatch, ["backup"])
    tried = []

    def fake_call(
        client,
        model,
        instructions,
        context,
        response_schema,
        store,
    ):
        tried.append(model)
        raise errors.ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "bad request",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )

    monkeypatch.setattr(gemini, "call_model", fake_call)

    with pytest.raises(GeminiRequestRejectedError):
        gemini.generate_structured_json(
            "i",
            {},
            {},
            file_search_store="fileSearchStores/test-store",
        )
    assert tried == ["primary"]


def test_gemini_requests_file_search_when_a_store_is_configured(monkeypatch):
    received = []

    monkeypatch.setattr(
        match_assessments,
        "GEMINI_FILE_SEARCH_STORE",
        "fileSearchStores/test-store",
    )

    def capture(
        instructions,
        context,
        response_schema,
        file_search_store=None,
    ):
        received.append(file_search_store)
        raise GeminiUnavailableError("stop")

    monkeypatch.setattr(
        match_assessments,
        "generate_structured_json",
        capture,
    )

    with pytest.raises(GeminiUnavailableError, match="stop"):
        match_assessments.ask_gemini({"route": {"distance_km": 1}})

    assert received == ["fileSearchStores/test-store"]


def test_missing_file_search_store_fails_without_an_assessment(monkeypatch):
    monkeypatch.setattr(match_assessments, "GEMINI_FILE_SEARCH_STORE", "")

    with pytest.raises(GeminiRequestRejectedError, match="File Search store"):
        match_assessments.ask_gemini({"shipment": {"origin": "Kitwe"}})


def test_gemini_rejects_missing_file_search_store(monkeypatch):
    configure_gemini(monkeypatch, [])
    monkeypatch.setattr(gemini, "GEMINI_FILE_SEARCH_STORE", "")

    with pytest.raises(
        GeminiRequestRejectedError,
        match="File Search store",
    ):
        gemini.generate_structured_json("i", {}, {})


def test_operating_cost_total_and_ai_estimate_stay_separate(
    db, pending_match, monkeypatch
):
    match, response = assess_with(db, pending_match, monkeypatch, None)

    assert response.operating_cost_total == Decimal("4090.00")
    assert response.estimated_total_cost == Decimal("4540.00")
    assert response.estimated_margin == Decimal("18500.00") - Decimal("4540.00")


def test_prompt_treats_operating_cost_as_authoritative_baseline():
    instructions = match_assessments.ASSESSMENT_INSTRUCTIONS

    assert "baseline must never be replaced" in instructions
    assert "not_quantified" in instructions
    assert "Never use ZMW 0" in instructions
    assert "Do not invent charges" in instructions
    assert "historical" in instructions
    assert "major_cost_factors" in ASSESSMENT_RESPONSE_SCHEMA["properties"]


def test_unquantified_factor_keeps_estimate_at_baseline(db, pending_match, monkeypatch):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "estimated_total_cost": 4090.00,
        "major_cost_factors": [
            {
                "factor": "Road condition and corridor congestion",
                "status": "not_quantified",
                "amount": None,
                "reason": "The risk is relevant but cannot be priced.",
                "calculation_basis": None,
                "citations": ["[DOC001, p. 14]"],
            }
        ],
        "_grounding_evidence": {
            "[DOC001, p. 14]": ["Road blocks caused delays and costs."]
        },
    }

    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    assert response.estimated_total_cost == Decimal("4090.00")
    assert response.assessment.major_cost_factors[0].amount is None


def test_known_document_id_alone_cannot_validate_money(db, pending_match, monkeypatch):
    ai_response = {
        **STUB_AI_ASSESSMENT,
        "estimated_total_cost": 4540.00,
        "major_cost_factors": [
            {
                "factor": "Border and customs delays",
                "status": "quantified",
                "amount": 450.00,
                "reason": "A document was cited without the retrieved passage.",
                "calculation_basis": {
                    "quantity": 1,
                    "unit": "day",
                    "rate_source": "configured_driver_rate",
                    "evidence_text": "unsupported passage text",
                },
                "citations": ["[DOC018, p. 20]"],
            }
        ],
        "_grounding_evidence": {"[DOC018, p. 20]": ["different retrieved passage"]},
    }

    match, response = assess_with(db, pending_match, monkeypatch, ai_response)

    assert response.assessment_status == "completed"
    assert response.estimated_total_cost == Decimal("4090.00")
    assert response.assessment.major_cost_factors[0].status == "not_quantified"
    assert response.assessment.major_cost_factors[0].amount is None


def test_assessment_runs_use_unique_ids_and_stale_worker_cannot_overwrite(
    db, pending_match, monkeypatch
):
    stub_assessment_services(monkeypatch)
    fleet, manager, truck, match = pending_match

    first_detail, first_run = start_assessment_with_run_id(
        db, manager.user_id, match.match_id
    )
    second_detail, second_run = start_assessment_with_run_id(
        db, manager.user_id, match.match_id
    )

    assert first_run != second_run
    assert second_detail["assessment_status"] == "running"

    finish_assessment(db, match.match_id, first_run)
    db.refresh(match)

    stored = match_assessments.read_stored_assessment(match)
    assert stored["assessment_run_id"] == second_run
    assert stored["assessment_status"] == "running"

    finish_assessment(db, match.match_id, second_run)
    db.refresh(match)

    stored = match_assessments.read_stored_assessment(match)
    assert stored["assessment_run_id"] == second_run
    assert stored["assessment_status"] == "completed"


def test_public_assessment_response_hides_internal_validation_details(
    db,
    pending_match,
    monkeypatch,
):
    match, response = assess_with(
        db,
        pending_match,
        monkeypatch,
        None,
    )

    payload = response.model_dump(mode="json")
    assessment = payload["assessment"]

    assert set(assessment) == {
        "summary",
        "major_cost_factors",
        "risk_factors",
        "limitations",
    }

    for factor in assessment["major_cost_factors"]:
        assert set(factor) == {
            "factor",
            "status",
            "amount",
            "reason",
        }

    serialized = str(assessment)

    assert "calculation_basis" not in serialized
    assert "evidence_text" not in serialized
    assert "rate_source" not in serialized
    assert "evidence_citations" not in serialized
    assert "assumptions" not in serialized
