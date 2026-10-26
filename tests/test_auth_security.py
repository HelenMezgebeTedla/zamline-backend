from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import config
import models
from security import rate_limit
from security.tokens import (
    ACCESS_TOKEN_MAX_MINUTES,
    decode_access_token,
    hash_refresh_token,
)
from services import sessions


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setattr(rate_limit, "ENABLED", True)
    rate_limit.clear_rate_limits()
    yield
    rate_limit.clear_rate_limits()


def _bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _login(client, payload, password=None, portal="shipper"):
    return client.post(
        "/users/login",
        json={
            "email": payload["company_email"],
            "password": password or payload["password"],
            "portal": portal,
        },
    )


class TestStrongPassword:
    @pytest.mark.parametrize(
        ("password", "message"),
        [
            ("Short1!", "at least 8 characters"),
            ("lowercase1!", "an uppercase letter"),
            ("UPPERCASE1!", "a lowercase letter"),
            ("NoNumbers!!", "a number"),
            ("NoSpecial123", "a special character"),
            ("Password1!", "too common"),
            (" Spaced123!", "start or end with a space"),
        ],
    )
    def test_weak_passwords_are_refused_at_signup(
        self, client, registration_payload, password, message
    ):
        response = client.post(
            "/users/register", json=registration_payload(password=password)
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]

    def test_password_cannot_contain_the_email(self, client, registration_payload):
        payload = registration_payload(
            company_email="helen.mezgebe@zamline-tests.com",
            password="Helen.Mezgebe2026!",
        )
        response = client.post("/users/register", json=payload)
        assert response.status_code == 422
        assert "email" in response.json()["detail"]

    def test_strong_password_is_accepted(self, client, registration_payload):
        response = client.post(
            "/users/register", json=registration_payload(password="Kafue#River2026")
        )
        assert response.status_code == 201

    def test_reset_password_needs_a_strong_password(
        self, client, register_and_login, mock_otp_email
    ):
        email = register_and_login("shipper")["payload"]["company_email"]
        client.post("/users/forgot-password", json={"email": email})
        response = client.post(
            "/users/reset-password",
            json={
                "email": email,
                "code": mock_otp_email[-1],
                "new_password": "weakpassword",
                "confirm_password": "weakpassword",
            },
        )
        assert response.status_code == 422


class TestSessions:
    def test_login_returns_short_access_token_and_refresh_token(
        self, register_and_login
    ):
        tokens = register_and_login("shipper")["tokens"]
        assert tokens["refresh_token"]
        assert tokens["expires_in"] <= ACCESS_TOKEN_MAX_MINUTES * 60
        claims = decode_access_token(tokens["access_token"])
        lifetime = claims["exp"] - claims["iat"]
        assert lifetime <= ACCESS_TOKEN_MAX_MINUTES * 60
        assert claims["sid"]

    def test_refresh_gives_new_tokens_and_old_refresh_stops_working(
        self, client, register_and_login
    ):
        tokens = register_and_login("shipper")["tokens"]
        first = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert first.status_code == 200
        renewed = first.json()
        assert renewed["refresh_token"] != tokens["refresh_token"]
        assert client.get("/users/me", headers=_bearer(renewed)).status_code == 200

        reused = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert reused.status_code == 401

    def test_reusing_an_old_refresh_token_ends_the_session(
        self, client, register_and_login
    ):
        tokens = register_and_login("shipper")["tokens"]
        renewed = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).json()
        client.post("/users/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert client.get("/users/me", headers=_bearer(renewed)).status_code == 401
        again = client.post(
            "/users/refresh", json={"refresh_token": renewed["refresh_token"]}
        )
        assert again.status_code == 401

    @pytest.mark.parametrize("token", ["", "not-a-real-token", "x" * 500])
    def test_bad_refresh_tokens_are_refused(self, client, token):
        response = client.post("/users/refresh", json={"refresh_token": token})
        assert response.status_code == 401

    def test_logout_ends_the_session(self, client, register_and_login):
        tokens = register_and_login("shipper")["tokens"]
        assert client.post("/users/logout", headers=_bearer(tokens)).status_code == 204
        assert client.get("/users/me", headers=_bearer(tokens)).status_code == 401
        refresh = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 401

    def test_logout_needs_a_token(self, client):
        assert client.post("/users/logout").status_code == 401

    def test_password_reset_ends_every_session(
        self, client, register_and_login, mock_otp_email
    ):
        account = register_and_login("shipper")
        tokens = account["tokens"]
        email = account["payload"]["company_email"]
        client.post("/users/forgot-password", json={"email": email})
        reset = client.post(
            "/users/reset-password",
            json={
                "email": email,
                "code": mock_otp_email[-1],
                "new_password": "Kafue#River2026",
                "confirm_password": "Kafue#River2026",
            },
        )
        assert reset.status_code == 200
        assert client.get("/users/me", headers=_bearer(tokens)).status_code == 401
        refresh = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 401

    def test_deleting_the_account_ends_every_session(self, client, register_and_login):
        tokens = register_and_login("shipper")["tokens"]
        assert client.delete("/users/me", headers=_bearer(tokens)).status_code == 204
        refresh = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 401

    @pytest.mark.parametrize(
        "later",
        [timedelta(days=8), timedelta(hours=25)],
        ids=["absolute", "idle"],
    )
    def test_expired_sessions_cannot_refresh(
        self, client, monkeypatch, register_and_login, later
    ):
        tokens = register_and_login("shipper")["tokens"]
        future = datetime.now(timezone.utc) + later
        monkeypatch.setattr(sessions, "_now", lambda: future)
        response = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert response.status_code == 401
        assert client.get("/users/me", headers=_bearer(tokens)).status_code == 401

    def test_active_use_keeps_the_session_alive(
        self, client, monkeypatch, register_and_login
    ):
        tokens = register_and_login("shipper")["tokens"]
        future = datetime.now(timezone.utc) + timedelta(hours=20)
        monkeypatch.setattr(sessions, "_now", lambda: future)
        renewed = client.post(
            "/users/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert renewed.status_code == 200
        future = future + timedelta(hours=20)
        refreshed = client.post(
            "/users/refresh", json={"refresh_token": renewed.json()["refresh_token"]}
        )
        assert refreshed.status_code == 200

    def test_refresh_token_is_stored_hashed(self, register_and_login):
        sessions.clear_sessions()
        tokens = register_and_login("shipper")["tokens"]
        stored = " ".join(sessions._cache.keys())
        assert tokens["refresh_token"] not in stored
        assert hash_refresh_token(tokens["refresh_token"]) in stored

    def test_logout_on_one_device_keeps_the_other(
        self, client, register_and_login, mock_otp_email
    ):
        account = register_and_login("shipper")
        first = account["tokens"]
        _login(client, account["payload"])
        second = client.post(
            "/users/verify-otp",
            json={
                "email": account["payload"]["company_email"],
                "code": mock_otp_email[-1],
                "portal": "shipper",
            },
        ).json()
        assert client.post("/users/logout", headers=_bearer(first)).status_code == 204
        assert client.get("/users/me", headers=_bearer(first)).status_code == 401
        assert client.get("/users/me", headers=_bearer(second)).status_code == 200

    def test_tampered_access_token_is_refused(self, client, register_and_login):
        tokens = register_and_login("shipper")["tokens"]
        claims = decode_access_token(tokens["access_token"])
        claims["sid"] = "00000000-0000-0000-0000-000000000000"
        forged = jwt.encode(claims, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
        response = client.get(
            "/users/me", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401


class TestOtpLifetime:
    def test_codes_last_at_most_five_minutes(self):
        assert 1 <= config.OTP_EXPIRE_MINUTES <= 5


class TestRateLimits:
    def test_login_is_limited_per_address(self, client, limits):
        body = {"email": "a@zamline-tests.com", "password": "x", "portal": "shipper"}
        codes = [client.post("/users/login", json=body).status_code for _ in range(11)]
        assert codes[-1] == 429
        assert 429 not in codes[:5]

    def test_too_many_requests_says_when_to_retry(self, client, limits):
        body = {"email": "a@zamline-tests.com"}
        for _ in range(3):
            client.post("/users/forgot-password", json=body)
        response = client.post("/users/forgot-password", json=body)
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
        assert response.json()["detail"] == rate_limit.TOO_MANY_REQUESTS

    @pytest.mark.parametrize(
        ("path", "body", "allowed"),
        [
            ("/users/resend-otp", {"email": "a@zamline-tests.com"}, 3),
            (
                "/users/reset-password",
                {
                    "email": "a@zamline-tests.com",
                    "code": "123456",
                    "new_password": "Kafue#River2026",
                    "confirm_password": "Kafue#River2026",
                },
                5,
            ),
            (
                "/users/verify-otp",
                {"email": "a@zamline-tests.com", "code": "123456", "portal": "shipper"},
                10,
            ),
            ("/users/refresh", {"refresh_token": "nope"}, 30),
        ],
    )
    def test_auth_routes_are_limited(self, client, limits, path, body, allowed):
        for _ in range(allowed):
            assert client.post(path, json=body).status_code != 429
        assert client.post(path, json=body).status_code == 429

    def test_signup_is_limited(self, client, limits, registration_payload):
        for _ in range(5):
            client.post("/users/register", json=registration_payload())
        response = client.post("/users/register", json=registration_payload())
        assert response.status_code == 429

    def test_account_locks_after_five_wrong_passwords(
        self, client, limits, register_and_login, monkeypatch
    ):
        payload = register_and_login("shipper")["payload"]
        monkeypatch.setattr(rate_limit, "ENABLED", True)
        for _ in range(5):
            assert _login(client, payload, "WrongPass123!").status_code == 401
            rate_limit.reset("login", "testclient")
        response = _login(client, payload)
        assert response.status_code == 429

    def test_successful_login_clears_failed_attempts(
        self, client, limits, register_and_login
    ):
        payload = register_and_login("shipper")["payload"]
        for _ in range(4):
            _login(client, payload, "WrongPass123!")
        assert _login(client, payload).status_code == 200
        for _ in range(4):
            _login(client, payload, "WrongPass123!")
            rate_limit.reset("login", "testclient")
        assert _login(client, payload).status_code == 200

    def test_every_endpoint_has_a_general_limit(self, client, limits, monkeypatch):
        monkeypatch.setattr(rate_limit, "GLOBAL_LIMIT_PER_MINUTE", 3)
        codes = [client.get("/health").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]

    def test_limit_uses_the_address_added_by_the_proxy(
        self, client, limits, monkeypatch
    ):
        monkeypatch.setattr(rate_limit, "GLOBAL_LIMIT_PER_MINUTE", 2)
        first = {"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}
        other = {"X-Forwarded-For": "1.1.1.1, 10.0.0.2"}
        for _ in range(2):
            client.get("/health", headers=first)
        assert client.get("/health", headers=first).status_code == 429
        assert client.get("/health", headers=other).status_code == 200

    def test_limits_can_be_turned_off(self, client):
        body = {"email": "a@zamline-tests.com"}
        codes = [
            client.post("/users/forgot-password", json=body).status_code
            for _ in range(6)
        ]
        assert 429 not in codes


class TestHttpProtection:
    def test_security_headers_are_sent(self, client):
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]

    def test_docs_still_load(self, client):
        response = client.get("/docs")
        assert response.status_code == 200
        assert "Content-Security-Policy" not in response.headers

    def test_very_large_requests_are_refused(self, client):
        response = client.post(
            "/users/login",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(50 * 1024 * 1024),
            },
        )
        assert response.status_code == 413

    def test_unexpected_errors_hide_details(self, db_session):
        from main import app

        def boom():
            raise RuntimeError("database password is hunter2")

        app.add_api_route("/__boom", boom)
        try:
            with TestClient(app, raise_server_exceptions=False) as test_client:
                response = test_client.get("/__boom")
        finally:
            app.router.routes = [
                route
                for route in app.router.routes
                if getattr(route, "path", "") != "/__boom"
            ]
        assert response.status_code == 500
        assert "hunter2" not in response.text
        assert response.json()["detail"] == (
            "Something went wrong. Please try again later."
        )


class TestRetention:
    def _old(self, db_session, action_type, entity_id, days):
        db_session.add(
            models.AuditLog(
                action_type=action_type,
                entity_type="user",
                entity_id=entity_id,
                created_at=datetime.now(timezone.utc) - timedelta(days=days),
            )
        )
        db_session.commit()

    def test_deleted_account_is_anonymised_after_30_days(
        self, client, db_session, register_and_login
    ):
        from services.retention import run_retention

        account = register_and_login("shipper")
        client.delete("/users/me", headers=account["headers"])
        user = db_session.query(models.User).one()
        self._old(db_session, "user_deletion_requested", user.user_id, 31)

        result = run_retention(db_session)
        db_session.refresh(user)
        assert result["users_anonymised"] == 1
        assert user.email.endswith("deleted.invalid")
        assert user.first_name == "Deleted"
        assert run_retention(db_session)["users_anonymised"] == 0

    def test_account_inside_grace_period_is_kept(
        self, client, db_session, register_and_login
    ):
        from services.retention import run_retention

        account = register_and_login("shipper")
        client.delete("/users/me", headers=account["headers"])
        assert run_retention(db_session)["users_anonymised"] == 0
        user = db_session.query(models.User).one()
        assert user.email == account["payload"]["company_email"]

    def test_deleted_company_is_anonymised_after_30_days(
        self, client, db_session, register_and_login
    ):
        from services.retention import run_retention

        account = register_and_login("fleet")
        client.delete(f"/companies/{account['company_id']}", headers=account["headers"])
        company = db_session.query(models.Company).one()
        self._old(db_session, "company_deletion_requested", company.company_id, 31)

        result = run_retention(db_session)
        db_session.refresh(company)
        assert result["companies_anonymised"] == 1
        assert company.company_email.endswith("deleted.invalid")
        assert company.business_name == "Deleted company"

    def test_audit_logs_older_than_12_months_are_deleted(self, db_session):
        from services.retention import run_retention

        self._old(db_session, "login", None, 400)
        self._old(db_session, "login", None, 10)
        assert run_retention(db_session)["audit_logs_deleted"] == 1
        assert db_session.query(models.AuditLog).count() == 1

    def test_retention_command_runs_and_closes_its_session(
        self, db_session, monkeypatch, capsys
    ):
        import database
        from services import retention

        closed = []
        monkeypatch.setattr(database, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: closed.append(True))
        retention.main()
        assert "audit_logs_deleted" in capsys.readouterr().out
        assert closed == [True]


class TestAccessLogging:
    def test_refused_requests_are_logged_without_tokens(self, client, caplog):
        with caplog.at_level("WARNING", logger="security.http"):
            client.get("/users/me", headers={"Authorization": "Bearer secret-token"})
        assert "Access denied: GET /users/me -> 401" in caplog.text
        assert "secret-token" not in caplog.text

    def test_company_create_is_limited(self, client, limits, registration_payload):
        for _ in range(5):
            client.post("/companies/create", json={})
        assert client.post("/companies/create", json={}).status_code == 429


class TestProductionDocs:
    def test_docs_are_hidden_in_production(self, monkeypatch, db_session):
        import importlib

        import main

        monkeypatch.setattr(config, "ENVIRONMENT", "production")
        production = importlib.reload(main)
        try:
            with TestClient(production.app) as api:
                for path in ("/docs", "/redoc", "/openapi.json"):
                    assert api.get(path).status_code == 404
                assert api.get("/health").status_code == 200
        finally:
            monkeypatch.setattr(config, "ENVIRONMENT", "test")
            importlib.reload(main)
