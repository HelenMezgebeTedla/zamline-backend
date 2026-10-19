import pytest

NEW_PASSWORD = "BrandNewPass456"


@pytest.fixture
def account(register_and_login):
    return register_and_login("shipper")["payload"]


def _forgot(client, email):
    return client.post("/users/forgot-password", json={"email": email})


def _reset(client, email, code, password=NEW_PASSWORD, confirm=None):
    return client.post(
        "/users/reset-password",
        json={
            "email": email,
            "code": code,
            "new_password": password,
            "confirm_password": password if confirm is None else confirm,
        },
    )


def _login(client, email, password):
    return client.post("/users/login", json={"email": email, "password": password})


class TestForgotPassword:
    def test_sends_a_reset_code(self, client, account, mock_otp_email):
        before = len(mock_otp_email)
        response = _forgot(client, account["company_email"])
        assert response.status_code == 200
        assert "reset code" in response.json()["message"]
        assert len(mock_otp_email) == before + 1

    def test_unknown_email_gets_the_same_answer(self, client, account, mock_otp_email):
        before = len(mock_otp_email)
        known = _forgot(client, account["company_email"]).json()
        unknown = _forgot(client, "nobody@zamline-tests.com")
        assert unknown.status_code == 200
        assert unknown.json() == known
        assert len(mock_otp_email) == before + 1

    def test_second_request_within_a_minute_is_not_resent(
        self, client, account, mock_otp_email
    ):
        _forgot(client, account["company_email"])
        before = len(mock_otp_email)
        assert _forgot(client, account["company_email"]).status_code == 200
        assert len(mock_otp_email) == before

    def test_invalid_email_is_rejected(self, client):
        assert _forgot(client, "not-an-email").status_code == 422


class TestResetPassword:
    def test_full_reset_flow(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        response = _reset(client, email, mock_otp_email[-1])
        assert response.status_code == 200
        assert "reset" in response.json()["message"]

        assert _login(client, email, account["password"]).status_code == 401
        assert _login(client, email, NEW_PASSWORD).status_code == 200

    def test_code_works_only_once(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        code = mock_otp_email[-1]
        assert _reset(client, email, code).status_code == 200
        assert _reset(client, email, code, "AnotherPass789").status_code == 400

    def test_wrong_code_is_refused(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        wrong = "000000" if mock_otp_email[-1] != "000000" else "111111"
        response = _reset(client, email, wrong)
        assert response.status_code == 400
        assert _login(client, email, account["password"]).status_code == 200

    def test_login_code_cannot_reset_the_password(
        self, client, account, mock_otp_email
    ):
        email = account["company_email"]
        _login(client, email, account["password"])
        login_code = mock_otp_email[-1]
        assert _reset(client, email, login_code).status_code == 400

    def test_reset_code_cannot_be_used_to_log_in(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        response = client.post(
            "/users/verify-otp", json={"email": email, "code": mock_otp_email[-1]}
        )
        assert response.status_code == 400

    def test_without_requesting_a_code_is_refused(self, client, account):
        assert _reset(client, account["company_email"], "123456").status_code == 400

    def test_unknown_email_is_refused(self, client):
        assert _reset(client, "nobody@zamline-tests.com", "123456").status_code == 400

    @pytest.mark.parametrize("code", ["12345", "abcdef", "1234567", ""])
    def test_code_must_be_six_digits(self, client, account, code):
        assert _reset(client, account["company_email"], code).status_code == 422

    def test_weak_password_is_refused(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        assert _reset(client, email, mock_otp_email[-1], "short").status_code == 422

    def test_passwords_must_match(self, client, account, mock_otp_email):
        email = account["company_email"]
        _forgot(client, email)
        response = _reset(client, email, mock_otp_email[-1], confirm="Different123")
        assert response.status_code == 422

    def test_too_many_wrong_codes_blocks_the_code(
        self, client, account, mock_otp_email
    ):
        email = account["company_email"]
        _forgot(client, email)
        real = mock_otp_email[-1]
        wrong = "000000" if real != "000000" else "111111"
        for _ in range(10):
            _reset(client, email, wrong)
        assert _reset(client, email, real).status_code == 400
        assert _login(client, email, account["password"]).status_code == 200


class TestEmailLinkRole:
    def test_reset_email_gets_the_account_role(self, client, account, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "services.otp.send_password_reset_email",
            lambda email, code, **kwargs: sent.append(kwargs),
        )
        _forgot(client, account["company_email"])
        assert sent == [{"role": "shipper"}]
