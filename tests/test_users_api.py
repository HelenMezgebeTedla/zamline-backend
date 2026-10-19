import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

import models
from config import JWT_ALGORITHM, JWT_SECRET, OTP_MAX_ATTEMPTS
from models.users import User
from services import otp as otp_service


class _CachedOTP:
    def __init__(self, user_id):
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_record", otp_service._load(user_id))

    def __getattr__(self, name):
        return getattr(self._record, name)

    def __setattr__(self, name, value):
        setattr(self._record, name, value)
        otp_service._cache.set(
            otp_service._key(self._user_id), self._record.to_json(), 600
        )


def _cached_otp(db_session):
    return _CachedOTP(db_session.query(User).one().user_id)


@pytest.fixture(autouse=True)
def _clear_otp_cache():
    otp_service.clear_otp_cache()
    yield
    otp_service.clear_otp_cache()


def _actions(db_session, action_type: str) -> int:
    return db_session.query(models.AuditLog).filter_by(action_type=action_type).count()


def _wrong_code(real_code: str) -> str:
    return "000000" if real_code != "000000" else "111111"


def _login(client, payload: dict):
    return client.post(
        "/users/login",
        json={"email": payload["company_email"], "password": payload["password"]},
    )


class TestRegistration:
    def test_register_shipper_creates_company_and_user(
        self, client, db_session, registration_payload
    ):
        payload = registration_payload("shipper")

        response = client.post("/users/register", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["role"] == "shipper"
        assert body["user"]["email"] == payload["company_email"]
        assert body["company"]["company_type"] == "shipper"
        assert body["company"]["verification_status"] == "pending"
        assert "password" not in response.text
        assert _actions(db_session, "user_registered") == 1

    def test_register_fleet_company_creates_fleet_manager(
        self, client, registration_payload
    ):
        response = client.post("/users/register", json=registration_payload("fleet"))

        assert response.status_code == 201
        assert response.json()["user"]["role"] == "fleet_manager"

    def test_password_is_stored_as_an_argon2_hash(
        self, client, db_session, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)

        user = db_session.query(models.User).one()
        assert user.password_hash != payload["password"]
        assert user.password_hash.startswith("$argon2")

    def test_duplicate_email_is_rejected_case_insensitively(
        self, client, registration_payload
    ):
        first = registration_payload(company_email="owner@zamline-tests.com")
        second = registration_payload(company_email="OWNER@zamline-tests.com")

        assert client.post("/users/register", json=first).status_code == 201
        assert client.post("/users/register", json=second).status_code == 409

    def test_duplicate_registration_number_is_rejected(
        self, client, db_session, registration_payload
    ):
        first = registration_payload(registration_number="120777777")
        second = registration_payload(registration_number=" 120 777 777 ")

        assert client.post("/users/register", json=first).status_code == 201
        assert client.post("/users/register", json=second).status_code == 409
        assert db_session.query(models.Company).count() == 1
        assert db_session.query(models.User).count() == 1

    @pytest.mark.parametrize(
        "overrides",
        [
            {"password": "short1"},
            {"password": "a" * 129},
            {"password": ""},
            {"business_name": "   "},
            {"business_name": "x" * 101},
            {"registration_number": "12"},
            {"registration_number": "REG 123!"},
            {"registration_number": "1" * 21},
            {"registration_number": "REG123456"},
            {"registration_number": "12345ABC"},
            {"business_name": "12345"},
            {"business_name": "Freight <script>"},
            {"phone_number": "not-a-phone"},
            {"phone_number": "+260"},
            {"first_name": "   "},
            {"first_name": "x" * 51},
            {"last_name": "x" * 51},
            {"first_name": "Helen2"},
            {"first_name": "12345"},
            {"last_name": "Mezgebe!"},
            {"last_name": "<b>Owner</b>"},
        ],
    )
    def test_invalid_input_is_rejected_without_creating_records(
        self, client, db_session, registration_payload, overrides
    ):
        payload = registration_payload(**overrides)

        response = client.post("/users/register", json=payload)

        assert response.status_code == 422
        assert db_session.query(models.Company).count() == 0
        assert db_session.query(models.User).count() == 0

    @pytest.mark.parametrize(
        "overrides",
        [{"company_email": "not-an-email"}, {"company_type": "carrier"}],
    )
    def test_schema_level_errors_return_422(
        self, client, registration_payload, overrides
    ):
        payload = registration_payload(**overrides)

        response = client.post("/users/register", json=payload)
        assert response.status_code == 422

    def test_phone_number_is_normalised(self, client, registration_payload):
        payload = registration_payload(phone_number="+260 97 123 4567")
        body = client.post("/users/register", json=payload).json()
        assert body["company"]["phone_number"] == "+260971234567"


class TestLoginAndOTP:
    def test_login_sends_a_six_digit_code(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()

        response = _login(client, payload)

        assert response.status_code == 200
        assert response.json()["otp_required"] is True
        assert len(mock_otp_email) == 1
        assert len(mock_otp_email[0]) == 6 and mock_otp_email[0].isdigit()

    def test_unknown_email_and_wrong_password_look_identical(
        self, client, db_session, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)

        unknown = client.post(
            "/users/login",
            json={"email": "nobody@zamline-tests.com", "password": "StrongPass123"},
        )
        wrong = client.post(
            "/users/login",
            json={"email": payload["company_email"], "password": "WrongPass123"},
        )

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()
        assert _actions(db_session, "login_failed") == 2

    def test_oversized_password_is_rejected_cleanly(self, client, registration_payload):
        payload = registration_payload()
        client.post("/users/register", json=payload)

        response = client.post(
            "/users/login",
            json={"email": payload["company_email"], "password": "a" * 5000},
        )

        assert response.status_code == 401

    def test_disabled_account_cannot_log_in(
        self, client, db_session, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        user = db_session.query(models.User).one()
        user.is_active = False
        db_session.commit()

        response = _login(client, payload)

        assert response.status_code == 403
        assert mock_otp_email == []

    def test_correct_code_returns_a_working_token(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)

        response = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": mock_otp_email[0]},
        )

        assert response.status_code == 200
        token = response.json()["access_token"]
        me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == payload["company_email"]

    def test_wrong_code_is_rejected_and_the_right_code_still_works(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)
        code = mock_otp_email[0]

        wrong = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": _wrong_code(code)},
        )
        right = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": code},
        )

        assert wrong.status_code == 400
        assert right.status_code == 200

    def test_code_can_only_be_used_once(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)
        body = {"email": payload["company_email"], "code": mock_otp_email[0]}

        assert client.post("/users/verify-otp", json=body).status_code == 200
        assert client.post("/users/verify-otp", json=body).status_code == 400

    def test_code_is_locked_after_too_many_wrong_attempts(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)
        code = mock_otp_email[0]

        for _ in range(OTP_MAX_ATTEMPTS):
            response = client.post(
                "/users/verify-otp",
                json={"email": payload["company_email"], "code": _wrong_code(code)},
            )
            assert response.status_code == 400

        final = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": code},
        )

        assert final.status_code == 400
        assert "Too many attempts" in final.json()["detail"]

    def test_expired_code_is_rejected(
        self, client, db_session, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)
        record = _cached_otp(db_session)
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        response = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": mock_otp_email[0]},
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", ""])
    def test_malformed_code_is_rejected(self, client, registration_payload, code):
        payload = registration_payload()
        client.post("/users/register", json=payload)

        response = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": code},
        )

        assert response.status_code == 422

    def test_verify_for_unknown_email_is_rejected(self, client):
        response = client.post(
            "/users/verify-otp",
            json={"email": "nobody@zamline-tests.com", "code": "123456"},
        )
        assert response.status_code == 400

    def test_failed_email_delivery_returns_503_and_stores_no_code(
        self, client, db_session, monkeypatch, registration_payload
    ):
        def _fail(_email, _code):
            raise RuntimeError("smtp down")

        payload = registration_payload()
        client.post("/users/register", json=payload)
        monkeypatch.setattr("services.otp.send_otp_email", _fail)

        response = _login(client, payload)

        assert response.status_code == 503
        assert otp_service._load(db_session.query(User).one().user_id) is None


class TestResendOTP:
    def test_unknown_and_known_emails_get_the_same_answer(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        otp_service.clear_otp_cache()

        unknown = client.post(
            "/users/resend-otp", json={"email": "nobody@zamline-tests.com"}
        )
        known = client.post(
            "/users/resend-otp", json={"email": payload["company_email"]}
        )

        assert unknown.status_code == known.status_code == 200
        assert unknown.json() == known.json()
        assert len(mock_otp_email) == 1

    def test_cooldown_blocks_a_second_code(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)

        client.post("/users/resend-otp", json={"email": payload["company_email"]})

        assert len(mock_otp_email) == 1

    def test_new_code_is_sent_after_the_cooldown(
        self, client, db_session, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        client.post("/users/register", json=payload)
        mock_otp_email.clear()
        _login(client, payload)
        record = _cached_otp(db_session)
        record.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db_session.commit()

        client.post("/users/resend-otp", json={"email": payload["company_email"]})

        assert len(mock_otp_email) == 2


class TestAuthentication:
    def test_missing_token_is_rejected(self, client):
        assert client.get("/users/me").status_code == 401

    def test_garbage_token_is_rejected(self, client):
        response = client.get("/users/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    def test_token_of_the_wrong_type_is_rejected(self, client, register_and_login):
        session = register_and_login()
        token = jwt.encode(
            {
                "sub": session["user_id"],
                "type": "refresh",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )

        response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_expired_token_is_rejected(self, client, register_and_login):
        session = register_and_login()
        token = jwt.encode(
            {
                "sub": session["user_id"],
                "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )

        response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_token_for_a_missing_user_is_rejected(self, client):
        token = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )

        response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401


class TestProfile:
    def test_get_me_returns_own_profile(self, client, register_and_login):
        session = register_and_login()

        response = client.get("/users/me", headers=session["headers"])

        assert response.status_code == 200
        assert response.json()["user_id"] == session["user_id"]
        assert response.json()["company_id"] == session["company_id"]

    @pytest.mark.parametrize("method", ["patch", "put"])
    def test_names_can_be_updated(self, client, db_session, register_and_login, method):
        session = register_and_login()

        response = getattr(client, method)(
            "/users/me",
            headers=session["headers"],
            json={"first_name": "  Grace ", "last_name": "Mwansa"},
        )

        assert response.status_code == 200
        assert response.json()["first_name"] == "Grace"
        assert response.json()["last_name"] == "Mwansa"
        assert _actions(db_session, "user_updated") == 1

    def test_empty_update_changes_nothing_and_is_not_logged(
        self, client, db_session, register_and_login
    ):
        session = register_and_login()

        response = client.patch("/users/me", headers=session["headers"], json={})

        assert response.status_code == 200
        assert _actions(db_session, "user_updated") == 0

    @pytest.mark.parametrize(
        "body", [{"first_name": "   "}, {"last_name": "x" * 51}, {"email": "bad"}]
    )
    def test_invalid_update_is_rejected(self, client, register_and_login, body):
        session = register_and_login()

        response = client.patch("/users/me", headers=session["headers"], json=body)

        assert response.status_code == 422

    def test_email_already_in_use_is_rejected(self, client, register_and_login):
        first = register_and_login()
        second = register_and_login()

        response = client.patch(
            "/users/me",
            headers=second["headers"],
            json={"email": first["payload"]["company_email"].upper()},
        )

        assert response.status_code == 409

    def test_delete_blocks_the_account(self, client, db_session, register_and_login):
        session = register_and_login()

        deleted = client.delete("/users/me", headers=session["headers"])

        assert deleted.status_code == 204
        assert client.get("/users/me", headers=session["headers"]).status_code == 401
        assert _login(client, session["payload"]).status_code == 403
        assert _actions(db_session, "user_deletion_requested") == 1


class TestSignupOTP:
    def test_register_sends_a_verification_code(
        self, client, mock_otp_email, registration_payload
    ):
        payload = registration_payload()
        response = client.post("/users/register", json=payload)
        assert response.status_code == 201
        assert len(mock_otp_email) == 1
        verified = client.post(
            "/users/verify-otp",
            json={"email": payload["company_email"], "code": mock_otp_email[-1]},
        )
        assert verified.status_code == 200

    def test_register_succeeds_even_if_email_fails(
        self, client, monkeypatch, registration_payload
    ):
        def _fail(_email, _code):
            raise RuntimeError("smtp down")

        monkeypatch.setattr("services.otp.send_otp_email", _fail)
        response = client.post("/users/register", json=registration_payload())
        assert response.status_code == 201

    def test_mismatched_confirm_password_is_rejected(
        self, client, registration_payload
    ):
        response = client.post(
            "/users/register",
            json=registration_payload(confirm_password="Different123"),
        )
        assert response.status_code == 422
