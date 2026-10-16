import smtplib
from email.mime.text import MIMEText

from config import (
    EMAIL_FROM,
    EMAIL_HOST,
    EMAIL_PASSWORD,
    EMAIL_PORT,
    EMAIL_USE_TLS,
    EMAIL_USERNAME,
    OTP_EXPIRE_MINUTES,
)

SMTP_TIMEOUT_SECONDS = 10


def send_otp_email(to_email: str, otp_code: str) -> None:
    if not (EMAIL_HOST and EMAIL_USERNAME and EMAIL_PASSWORD):
        raise RuntimeError("Email delivery is not configured")

    message = MIMEText(
        f"Your ZamLine verification code is: {otp_code}\n\n"
        f"This code will expire in {OTP_EXPIRE_MINUTES} minutes.",
        "plain",
    )
    message["From"] = EMAIL_FROM or EMAIL_USERNAME
    message["To"] = to_email
    message["Subject"] = "ZamLine - Your Verification Code"

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if EMAIL_USE_TLS:
            server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(message)
