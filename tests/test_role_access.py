import uuid

import pytest

import models


def _set_status(db_session, company_id, status):
    company = db_session.get(models.Company, uuid.UUID(company_id))
    company.verification_status = status
    db_session.commit()


@pytest.fixture
def verified_shipper(db_session, register_and_login):
    session = register_and_login("shipper")
    _set_status(db_session, session["company_id"], models.VerificationStatus.VERIFIED)
    return session


@pytest.fixture
def verified_fleet(db_session, register_and_login):
    session = register_and_login("fleet")
    _set_status(db_session, session["company_id"], models.VerificationStatus.VERIFIED)
    return session


class TestShipmentRoutesAreForShippersOnly:
    def test_verified_shipper_can_list_shipments(self, client, verified_shipper):
        response = client.get("/shipments", headers=verified_shipper["headers"])
        assert response.status_code == 200

    def test_fleet_manager_is_refused(self, client, verified_fleet):
        response = client.get("/shipments", headers=verified_fleet["headers"])
        assert response.status_code == 403

    def test_unverified_shipper_is_refused(self, client, register_and_login):
        session = register_and_login("shipper")
        response = client.get("/shipments", headers=session["headers"])
        assert response.status_code == 403
        assert response.json()["detail"] == "Company is not verified"

    @pytest.mark.parametrize("status", ["resubmit", "rejected", "pending"])
    def test_failed_or_pending_verification_is_refused(
        self, client, db_session, register_and_login, status
    ):
        session = register_and_login("shipper")
        _set_status(
            db_session, session["company_id"], models.VerificationStatus(status)
        )
        response = client.get("/shipments", headers=session["headers"])
        assert response.status_code == 403

    def test_no_token_is_refused(self, client):
        assert client.get("/shipments").status_code == 401


class TestMatchRoutesAreForFleetManagersOnly:
    def test_verified_fleet_can_see_opportunities(self, client, verified_fleet):
        response = client.get(
            "/shipment-matches/opportunities", headers=verified_fleet["headers"]
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_shipper_is_refused(self, client, verified_shipper):
        for method, path in (
            ("get", "/shipment-matches/opportunities"),
            ("post", "/shipment-matches/generate"),
        ):
            response = getattr(client, method)(
                path, headers=verified_shipper["headers"]
            )
            assert response.status_code == 403

    def test_unverified_fleet_is_refused(self, client, register_and_login):
        session = register_and_login("fleet")
        response = client.post("/shipment-matches/generate", headers=session["headers"])
        assert response.status_code == 403
        assert response.json()["detail"] == "Company is not verified"

    def test_cannot_read_another_fleet_company(
        self, client, verified_fleet, db_session, register_and_login
    ):
        other = register_and_login("fleet")
        _set_status(db_session, other["company_id"], models.VerificationStatus.VERIFIED)
        response = client.get(
            "/shipment-matches/opportunities",
            params={"company_id": other["company_id"]},
            headers=verified_fleet["headers"],
        )
        assert response.status_code == 403

    def test_no_token_is_refused(self, client, sample_fleet_company):
        response = client.get(
            "/shipment-matches/opportunities",
            params={"company_id": str(sample_fleet_company.company_id)},
        )
        assert response.status_code == 401


class TestRoleMustMatchCompanyType:
    def test_shipper_user_in_fleet_company_is_refused(
        self, client, db_session, verified_shipper
    ):
        company = db_session.get(
            models.Company, uuid.UUID(verified_shipper["company_id"])
        )
        company.company_type = models.CompanyType.FLEET
        db_session.commit()

        response = client.get("/shipments", headers=verified_shipper["headers"])
        assert response.status_code == 403

    def test_registration_gives_each_company_type_its_own_role(
        self, client, register_and_login
    ):
        shipper = register_and_login("shipper")
        fleet = register_and_login("fleet")
        assert client.get("/users/me", headers=shipper["headers"]).json()["role"] == (
            "shipper"
        )
        assert client.get("/users/me", headers=fleet["headers"]).json()["role"] == (
            "fleet_manager"
        )
