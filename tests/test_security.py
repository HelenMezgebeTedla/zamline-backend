import smtplib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import JWT_ALGORITHM, JWT_SECRET
from security import email as email_module
from security.password import hash_password, verify_password
from security.tokens import create_access_token, decode_access_token


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        result = hash_password("SecurePass123")
        assert isinstance(result, str)
        assert len(result) > 0
        assert result != "SecurePass123"

    def test_verify_password_correct(self):
        hashed = hash_password("MyPassword123")
        assert verify_password("MyPassword123", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = hash_password("MyPassword123")
        assert verify_password("WrongPassword", hashed) is False

    def test_hash_password_different_salts(self):
        hash1 = hash_password("Password123")
        hash2 = hash_password("Password123")
        assert hash1 != hash2

    def test_verify_password_invalid_hash(self):
        assert verify_password("Password123", "invalid_hash") is False

    def test_hash_password_empty_string(self):
        result = hash_password("")
        assert isinstance(result, str)
        assert verify_password("", result) is True


def _encode(payload: dict, secret: str = JWT_SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _claims(**overrides) -> dict:
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "shipper",
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    claims.update(overrides)
    return claims


class TestJWTTokens:
    def test_create_access_token_returns_string(self):
        token = create_access_token(uuid.uuid4(), "shipper")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token_returns_payload(self):
        user_id = uuid.uuid4()
        payload = decode_access_token(create_access_token(user_id, "fleet_manager"))
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "fleet_manager"
        assert payload["type"] == "access"

    def test_decode_invalid_token_raises(self):
        with pytest.raises(jwt.PyJWTError):
            decode_access_token("invalid_token")

    def test_token_type_mismatch_raises(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(_encode(_claims(type="refresh")))

    def test_expired_token_raises(self):
        expired = _claims(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(_encode(expired))

    def test_token_signed_with_another_secret_raises(self):
        forged = _encode(_claims(), secret="a-different-secret-of-sufficient-length")
        with pytest.raises(jwt.InvalidSignatureError):
            decode_access_token(forged)

    def test_token_without_expiry_raises(self):
        claims = _claims()
        del claims["exp"]
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(_encode(claims))

    def test_missing_secret_is_an_error(self, monkeypatch):
        monkeypatch.setattr("security.tokens.JWT_SECRET", "")
        with pytest.raises(RuntimeError):
            create_access_token(uuid.uuid4(), "shipper")


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.actions: list[str] = []
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.actions.append("starttls")

    def login(self, username, password):
        self.actions.append(f"login:{username}")

    def send_message(self, message):
        self.message = message


@pytest.fixture
def smtp_settings(monkeypatch):
    values = {
        "EMAIL_HOST": "smtp.zamline-tests.com",
        "EMAIL_PORT": 587,
        "EMAIL_USERNAME": "mailer",
        "EMAIL_PASSWORD": "mailer-password",
        "EMAIL_FROM": "no-reply@zamline-tests.com",
        "EMAIL_USE_TLS": True,
    }
    for name, value in values.items():
        monkeypatch.setattr(email_module, name, value)
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return values


class TestOTPEmail:
    def test_unconfigured_email_is_an_error(self, monkeypatch):
        monkeypatch.setattr(email_module, "EMAIL_HOST", "")
        with pytest.raises(RuntimeError):
            email_module.send_otp_email("user@zamline-tests.com", "123456")

    def test_missing_password_is_an_error(self, smtp_settings, monkeypatch):
        monkeypatch.setattr(email_module, "EMAIL_PASSWORD", "")
        with pytest.raises(RuntimeError):
            email_module.send_otp_email("user@zamline-tests.com", "123456")
        assert FakeSMTP.instances == []

    def test_email_is_sent_with_tls_and_login(self, smtp_settings):
        email_module.send_otp_email("user@zamline-tests.com", "123456")

        server = FakeSMTP.instances[0]
        assert server.host == "smtp.zamline-tests.com"
        assert server.actions == ["starttls", "login:mailer"]
        assert server.message["To"] == "user@zamline-tests.com"
        assert server.message["From"] == "ZamLine <no-reply@zamline-tests.com>"
        assert server.message["Subject"] == "123456 is your ZamLine verification code"
        plain = server.message.get_body(preferencelist=("plain",)).get_content()
        html = server.message.get_body(preferencelist=("html",)).get_content()
        assert "123456" in plain
        assert "Verify your email" in html
        for digit in "123456":
            assert f">{digit}</td>" in html

    def test_email_matches_the_zamline_design(self):
        html = email_module.build_otp_html("482915")
        assert "ZamLine" in html
        assert "#0b1f3a" in html and "#1a9bb8" in html
        assert "expires in" in html

    def test_shipper_code_opens_the_shipper_verify_page(self):
        message = email_module.build_otp_message(
            "owner+1@zamline-tests.com", "482915", role="shipper"
        )
        html = message.get_body(("html",)).get_content()
        assert "Tap your code" in html
        assert (
            'href="http://localhost:3000/shipper/verify-email'
            '#email=owner%2B1%40zamline-tests.com&amp;code=482915"'
        ) in html

    def test_fleet_code_opens_the_fleet_page(self):
        assert email_module.code_link(
            "a@b.com", "111222", "fleet_manager", email_module.RESET
        ) == ("http://localhost:3000/fleet/forgot-password#email=a%40b.com&code=111222")

    def test_without_a_role_the_code_is_plain_text(self):
        html = email_module.build_otp_html("482915")
        assert "<a " not in html
        assert 'user-select:all;">482915</span>' in html

    def test_without_frontend_url_there_is_no_link(self, monkeypatch):
        monkeypatch.setattr(email_module, "FRONTEND_URL", "")
        assert (
            email_module.code_link("a@b.com", "1", "shipper", email_module.VERIFY)
            is None
        )

    def test_sender_name_is_kept_when_already_given(self, monkeypatch):
        monkeypatch.setattr(email_module, "EMAIL_FROM", "Nexa Team <team@x.com>")
        assert email_module.sender_address() == "Nexa Team <team@x.com>"

    def test_email_has_no_logo_image(self):
        message = email_module.build_otp_message("user@zamline-tests.com", "123456")
        types = [part.get_content_type() for part in message.walk()]
        assert "image/png" not in types
        assert "<img" not in message.get_body(("html",)).get_content()

    def test_password_reset_email_uses_the_same_design(self, smtp_settings):
        email_module.send_password_reset_email(
            "user@zamline-tests.com", "654321", role="fleet_manager"
        )
        message = FakeSMTP.instances[0].message
        assert message["Subject"] == "654321 is your ZamLine password reset code"
        assert message["From"] == "ZamLine <no-reply@zamline-tests.com>"
        html = message.get_body(("html",)).get_content()
        assert "Reset your password" in html
        assert "/fleet/forgot-password#email=" in html
        assert "code=654321" in html
        assert "654321" in message.get_body(("plain",)).get_content()

    def test_tls_can_be_disabled_for_local_relays(self, smtp_settings, monkeypatch):
        monkeypatch.setattr(email_module, "EMAIL_USE_TLS", False)
        email_module.send_otp_email("user@zamline-tests.com", "123456")
        assert FakeSMTP.instances[0].actions == ["login:mailer"]
