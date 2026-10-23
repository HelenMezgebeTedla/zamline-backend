from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.companies import CompanyType, VerificationStatus
from models.shipment_matches import ManagerDecision, ShipmentMatch
from models.shipments import Shipment, ShipmentStatus
from models.trucks import AvailabilityStatus, Truck
from models.users import User, UserRole
from repositories import shipment_matches as match_repository
from services.errors import (
    ConflictError,
    NotAllowedError,
    NotFoundError,
    ExternalServiceError,
)
from services.match_assessments import (
    apply_ai_assessment,
    build_assessment_context,
    build_match_detail,
    mark_assessment_failed,
    record_operating_costs,
    request_ai_assessment,
    assessment_run_id,
    assessment_run_is_current,
)
from services.operating_costs import calculate_operating_costs
from services.routing import (
    geocode_address,
    get_route_between_coordinates,
    get_route_summary,
)
from uuid import uuid4
from services import reservations as reservation_service

SHIPMENT_NOT_AVAILABLE = "This shipment is no longer available."


class ActorNotFoundError(NotFoundError):
    pass


class ActorNotAllowedError(NotAllowedError):
    pass


class FleetCompanyNotFoundError(NotFoundError):
    pass


class FleetCompanyNotEligibleError(NotAllowedError):
    pass


class MatchNotFoundError(NotFoundError):
    pass


class MatchAccessDeniedError(NotAllowedError):
    pass


class ShipmentNoLongerAvailableError(ConflictError):
    pass


def get_active_user(db: Session, actor_user_id):
    user = match_repository.get_user(db, actor_user_id)

    if user is None:
        raise ActorNotFoundError("User was not found")

    if not user.is_active:
        raise ActorNotAllowedError("User account is not active")

    return user


def get_eligible_fleet_company(db: Session, company_id):
    company = match_repository.get_company(db, company_id)

    if company is None:
        raise FleetCompanyNotFoundError("Fleet company was not found")

    if company.company_type != CompanyType.FLEET:
        raise FleetCompanyNotEligibleError("Company is not a fleet company")

    if company.verification_status != VerificationStatus.VERIFIED:
        raise FleetCompanyNotEligibleError("Fleet company is not verified")

    return company


def get_fleet_manager(db: Session, actor_user_id):
    user = get_active_user(db, actor_user_id)

    if user.role != UserRole.FLEET_MANAGER:
        raise ActorNotAllowedError("Only Fleet Managers can perform this action")

    get_eligible_fleet_company(db, user.company_id)

    return user


def truck_matches_shipment(truck: Truck, shipment: Shipment):
    if truck.body_type != shipment.required_body_type:
        return False

    if truck.capacity_kg < shipment.weight_kg:
        return False

    return True


def match_is_still_eligible(match: ShipmentMatch, company_id):
    shipment = match.shipment
    truck = match.truck

    if match.manager_decision != ManagerDecision.PENDING:
        return False

    if shipment.status != ShipmentStatus.OPEN:
        return False

    if truck.company_id != company_id:
        return False

    if shipment.company_id == company_id:
        return False

    if truck.availability_status != AvailabilityStatus.AVAILABLE:
        return False

    return truck_matches_shipment(truck, shipment)


def get_own_match(db: Session, actor: User, match_id):
    match = match_repository.get_match_by_id(db, match_id)

    if match is None:
        raise MatchNotFoundError("Match was not found")

    if match.truck.company_id != actor.company_id:
        raise MatchAccessDeniedError("You do not have access to this match")

    return match


def list_eligible_matches(db: Session, company_id):
    matches = match_repository.get_pending_matches_for_company(db, company_id)

    eligible_matches = []
    for match in matches:
        if match_is_still_eligible(match, company_id):
            eligible_matches.append(match)

    return eligible_matches


def generate_matches_for_fleet_manager(db: Session, actor_user_id):
    actor = get_fleet_manager(db, actor_user_id)
    company_id = actor.company_id

    trucks = match_repository.get_available_trucks_for_company(db, company_id)
    shipments = match_repository.get_open_shipments(db)

    created = False

    for shipment in shipments:
        if shipment.company_id == company_id:
            continue

        for truck in trucks:
            if not truck_matches_shipment(truck, shipment):
                continue

            existing_match = match_repository.get_match(
                db,
                shipment.shipment_id,
                truck.truck_id,
            )

            if existing_match is not None:
                continue

            match_repository.create_match(db, shipment, truck)
            created = True

    if created:
        db.commit()

    return list_eligible_matches(db, company_id)


def list_opportunities_for_fleet_manager(db: Session, actor_user_id):
    actor = get_fleet_manager(db, actor_user_id)

    return list_eligible_matches(db, actor.company_id)


def geocode_location_for_fleet_manager(db: Session, actor_user_id, text, size):
    get_fleet_manager(db, actor_user_id)
    return geocode_address(text, size)


def estimate_route_for_fleet_manager(
    db: Session,
    actor_user_id,
    origin_latitude,
    origin_longitude,
    destination_latitude,
    destination_longitude,
):
    get_fleet_manager(db, actor_user_id)
    return get_route_between_coordinates(
        origin_latitude, origin_longitude, destination_latitude, destination_longitude
    )


def get_eligible_own_match(db: Session, actor: User, match_id):
    match = get_own_match(db, actor, match_id)

    if not match_is_still_eligible(match, actor.company_id):
        raise ShipmentNoLongerAvailableError(SHIPMENT_NOT_AVAILABLE)

    return match


def get_match_detail(db: Session, actor_user_id, match_id):
    actor = get_fleet_manager(db, actor_user_id)
    match = get_eligible_own_match(db, actor, match_id)

    return build_match_detail(match)


def start_assessment(db: Session, actor_user_id, match_id):
    actor = get_fleet_manager(db, actor_user_id)
    match = get_eligible_own_match(db, actor, match_id)
    company = match_repository.get_company(db, actor.company_id)

    route = get_route_summary(match.shipment)
    costs = calculate_operating_costs(company, match.truck, route)

    record_operating_costs(match, route, costs, str(uuid4()))
    db.commit()

    return build_match_detail(match)


def start_assessment_with_run_id(db: Session, actor_user_id, match_id):
    detail = start_assessment(db, actor_user_id, match_id)
    match = match_repository.get_match_by_id(db, match_id)
    run_id = assessment_run_id(match)
    if run_id is None:
        raise RuntimeError("Assessment run ID was not stored")
    return detail, run_id


def finish_assessment(db: Session, match_id, run_id=None):
    match = match_repository.get_match_by_id(db, match_id)
    if match is None:
        raise MatchNotFoundError("Match was not found")

    active_run_id = assessment_run_id(match)
    run_id = str(run_id or active_run_id or "")
    if not run_id or active_run_id != run_id:
        return build_match_detail(match)

    try:
        company = match_repository.get_company(db, match.truck.company_id)
        route = get_route_summary(match.shipment)
        costs = calculate_operating_costs(company, match.truck, route)
        context = build_assessment_context(match, company, route, costs)
        assessment = request_ai_assessment(context)

        db.refresh(match)
        if not assessment_run_is_current(match, run_id):
            return build_match_detail(match)

        apply_ai_assessment(match, assessment, run_id)
    except ExternalServiceError as error:
        db.refresh(match)
        if not assessment_run_is_current(match, run_id):
            return build_match_detail(match)
        mark_assessment_failed(match, str(error), run_id)

    db.commit()
    return build_match_detail(match)


def assess_match(db: Session, actor_user_id, match_id):
    _, run_id = start_assessment_with_run_id(db, actor_user_id, match_id)
    return finish_assessment(db, match_id, run_id)


def decide_match(db: Session, actor_user_id, match_id, decision: ManagerDecision):
    actor = get_fleet_manager(db, actor_user_id)
    get_own_match(db, actor, match_id)
    match = match_repository.lock_match(db, match_id)

    if not match_is_still_eligible(match, actor.company_id):
        db.rollback()
        raise ShipmentNoLongerAvailableError(SHIPMENT_NOT_AVAILABLE)

    match.manager_decision = decision
    match.user_id = actor.user_id
    match.decided_at = datetime.now(timezone.utc)
    db.commit()

    return match


def accept_match(db: Session, actor_user_id, match_id):
    actor = get_fleet_manager(db, actor_user_id)
    get_eligible_own_match(db, actor, match_id)
    reservation_service.accept_match(db, actor, match_id)
    return match_repository.get_match_by_id(db, match_id)


def skip_match(db: Session, actor_user_id, match_id):
    return decide_match(db, actor_user_id, match_id, ManagerDecision.DECLINED)
