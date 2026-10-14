from sqlalchemy.orm import Session

from models.companies import CompanyType, VerificationStatus
from models.shipments import Shipment
from models.trucks import Truck
from repositories import shipment_matches as match_repository


class FleetCompanyNotFoundError(ValueError):
    pass


class FleetCompanyNotEligibleError(ValueError):
    pass


def get_eligible_fleet_company(db: Session, company_id):
    company = match_repository.get_company(db, company_id)
    if company is None:
        raise FleetCompanyNotFoundError("Fleet company was not found")
    if company.company_type != CompanyType.FLEET:
        raise FleetCompanyNotEligibleError("Company is not a fleet company")
    if company.verification_status != VerificationStatus.VERIFIED:
        raise FleetCompanyNotEligibleError("Fleet company is not verified")
    return company


def truck_matches_shipment(truck: Truck, shipment: Shipment):
    if truck.body_type != shipment.required_body_type:
        return False
    if truck.capacity_kg < shipment.weight_kg:
        return False
    return True


def generate_matches_for_fleet_company(db: Session, company_id):
    company = get_eligible_fleet_company(db, company_id)
    trucks = match_repository.get_available_trucks_for_company(db, company.company_id)
    shipments = match_repository.get_open_shipments(db)

    created = False
    for shipment in shipments:
        if shipment.company_id == company.company_id:
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

    return match_repository.get_current_matches_for_company(db, company.company_id)


def list_matches_for_fleet_company(db: Session, company_id):
    company = get_eligible_fleet_company(db, company_id)
    return match_repository.get_current_matches_for_company(db, company.company_id)
