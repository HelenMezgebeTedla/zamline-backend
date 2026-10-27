import uuid

import pytest

import models
from models.users import TERMS_VERSION, User
from services import otp as otp_service
from services.auth import TERMS_REQUIRED


@pytest.fixture(autouse=True)
def _clear_otp_cache():
    otp_service.clear_otp_cache()
    yield
    otp_service.clear_otp_cache()


def _forget_terms(db_session, user_id):
    user = db_session.query(User).filter_by(user_id=uuid.UUID(user_id)).one()
    user.terms_accepted_at = None
    user.terms_version = None
    db_session.commit()


def _audit_count(db_session, action_type):
    return db_session.query(models.AuditLog).filter_by(action_type=action_type).count()


class TestRegistration:
    def test_sign_up_without_accepting_terms_is_refused(
        self, client, db_session, registration_payload
    ):
        response = client.post(
            "/users/register", json=registration_payload(accept_terms=False)
        )
        assert response.status_code == 422
        assert "Terms and Policy" in response.text
        assert db_session.query(User).count() == 0

    def test_sign_up_with_terms_missing_is_refused(
        self, client, db_session, registration_payload
    ):
        payload = registration_payload()
        payload.pop("accept_terms")
        assert client.post("/users/register", json=payload).status_code == 422
        assert db_session.query(User).count() == 0

    def test_sign_up_records_the_accepted_terms(
        self, client, db_session, registration_payload
    ):
        response = client.post("/users/register", json=registration_payload())
        assert response.status_code == 201
        body = response.json()["user"]
        assert body["terms_accepted"] is True
        assert body["terms_version"] == TERMS_VERSION
        assert body["terms_accepted_at"]
        user = db_session.query(User).one()
        assert user.terms_accepted_at is not None
        assert user.terms_version == TERMS_VERSION


class TestExistingUsers:
    def test_protected_routes_are_refused_until_terms_are_accepted(
        self, client, db_session, register_and_login
    ):
        account = register_and_login("shipper")
        _forget_terms(db_session, account["user_id"])

        response = client.get(
            f"/companies/{account['company_id']}", headers=account["headers"]
        )
        assert response.status_code == 403
        assert response.json()["detail"] == TERMS_REQUIRED

        assert (
            client.patch(
                "/users/me", json={"first_name": "Mary"}, headers=account["headers"]
            ).status_code
            == 403
        )

    def test_profile_shows_terms_are_missing(
        self, client, db_session, register_and_login
    ):
        account = register_and_login("fleet")
        _forget_terms(db_session, account["user_id"])

        response = client.get("/users/me", headers=account["headers"])
        assert response.status_code == 200
        assert response.json()["terms_accepted"] is False
        assert response.json()["terms_version"] is None

    def test_accepting_terms_unlocks_the_system(
        self, client, db_session, register_and_login
    ):
        account = register_and_login("shipper")
        _forget_terms(db_session, account["user_id"])

        accepted = client.post("/users/accept-terms", headers=account["headers"])
        assert accepted.status_code == 200
        assert accepted.json()["terms_accepted"] is True
        assert accepted.json()["terms_version"] == TERMS_VERSION
        assert _audit_count(db_session, "terms_accepted") == 1

        response = client.get(
            f"/companies/{account['company_id']}", headers=account["headers"]
        )
        assert response.status_code == 200

    def test_accepting_twice_keeps_one_record(
        self, client, db_session, register_and_login
    ):
        account = register_and_login("shipper")
        _forget_terms(db_session, account["user_id"])

        client.post("/users/accept-terms", headers=account["headers"])
        first = db_session.query(User).one().terms_accepted_at
        again = client.post("/users/accept-terms", headers=account["headers"])

        assert again.status_code == 200
        assert db_session.query(User).one().terms_accepted_at == first
        assert _audit_count(db_session, "terms_accepted") == 1

    def test_new_terms_version_must_be_accepted_again(
        self, client, db_session, register_and_login, monkeypatch
    ):
        account = register_and_login("shipper")
        monkeypatch.setattr("models.users.TERMS_VERSION", "2.0")
        monkeypatch.setattr("services.users.TERMS_VERSION", "2.0")

        response = client.get(
            f"/companies/{account['company_id']}", headers=account["headers"]
        )
        assert response.status_code == 403

        accepted = client.post("/users/accept-terms", headers=account["headers"])
        assert accepted.json()["terms_version"] == "2.0"
        response = client.get(
            f"/companies/{account['company_id']}", headers=account["headers"]
        )
        assert response.status_code == 200

    def test_logout_still_works_without_terms(
        self, client, db_session, register_and_login
    ):
        account = register_and_login("shipper")
        _forget_terms(db_session, account["user_id"])

        response = client.post("/users/logout", headers=account["headers"])
        assert response.status_code == 204

    def test_accept_terms_needs_a_valid_login(self, client):
        assert client.post("/users/accept-terms").status_code == 401
        response = client.post(
            "/users/accept-terms", headers={"Authorization": "Bearer not-a-token"}
        )
        assert response.status_code == 401
