import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape

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
SENDER_NAME = "ZamLine"

NAVY = "#0b1f3a"
BLUE = "#1d3d78"
TEAL = "#1a9bb8"
PAGE_BG = "#f2f9fd"
BOX_BG = "#dceefb"
MUTED = "#4a5b6e"
FONT = "'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

VERIFY = {
    "subject": "{code} is your ZamLine verification code",
    "label": "Email verification",
    "title": "Verify your email",
    "intro": "Enter this 6-digit code on the ZamLine verification page.",
    "ignore": "If you did not request this code, you can safely ignore this email.",
}
RESET = {
    "subject": "{code} is your ZamLine password reset code",
    "label": "Password reset",
    "title": "Reset your password",
    "intro": "Enter this 6-digit code on the ZamLine reset password page.",
    "ignore": (
        "If you did not ask to reset your password, ignore this email. "
        "Your password will not change."
    ),
}


def build_otp_text(otp_code: str, content: dict = VERIFY) -> str:
    return (
        f"ZamLine - {content['title']}\n\n"
        f"Your code is: {otp_code}\n\n"
        f"This code will expire in {OTP_EXPIRE_MINUTES} minutes.\n"
        f"{content['ignore']}\n"
    )


def build_otp_html(otp_code: str, content: dict = VERIFY) -> str:
    code = escape(otp_code)
    digits = "".join(
        f'<td style="width:44px;height:56px;background:{BOX_BG};border-radius:10px;'
        f"text-align:center;vertical-align:middle;font-family:{FONT};font-size:28px;"
        f'font-weight:700;color:{BLUE};">{escape(digit)}</td>'
        '<td style="width:8px;"></td>'
        for digit in otp_code
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:{PAGE_BG};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{PAGE_BG};padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:520px;background:#ffffff;border-radius:16px;
                    overflow:hidden;box-shadow:0 8px 24px rgba(11,31,58,0.08);">
        <tr><td style="background:{NAVY};padding:28px 24px;text-align:center;">
          <p style="margin:0;font-family:{FONT};font-size:24px;font-weight:700;
                    color:#ffffff;letter-spacing:0.5px;">ZamLine</p>
          <p style="margin:6px 0 0;font-family:{FONT};font-size:12px;
                    letter-spacing:2px;text-transform:uppercase;color:{TEAL};">
            Moving freight forward</p>
        </td></tr>
        <tr><td style="padding:32px 28px 8px;text-align:center;">
          <p style="margin:0 0 8px;font-family:{FONT};font-size:12px;font-weight:600;
                    letter-spacing:2px;text-transform:uppercase;color:{TEAL};">
            {content["label"]}</p>
          <h1 style="margin:0 0 12px;font-family:{FONT};font-size:26px;
                     font-weight:700;color:{NAVY};">{content["title"]}</h1>
          <p style="margin:0 0 24px;font-family:{FONT};font-size:15px;
                    line-height:1.6;color:{MUTED};">
            {content["intro"]}</p>
          <table role="presentation" cellpadding="0" cellspacing="0" align="center"
                 style="margin:0 auto 20px;"><tr>{digits}</tr></table>
          <p style="margin:0 0 6px;font-family:{FONT};font-size:12px;font-weight:600;
                    letter-spacing:1px;text-transform:uppercase;color:{MUTED};">
            Copy your code</p>
          <table role="presentation" cellpadding="0" cellspacing="0" align="center"
                 style="margin:0 auto 8px;"><tr>
            <td style="border:2px dashed {TEAL};border-radius:10px;padding:10px 22px;
                       background:#ffffff;font-family:'Courier New',monospace;
                       font-size:22px;font-weight:700;color:{NAVY};
                       -webkit-user-select:all;user-select:all;">{code}</td>
          </tr></table>
          <p style="margin:0 0 24px;font-family:{FONT};font-size:12px;color:{MUTED};">
            Tap and hold (or double-click) the code above to copy it.</p>
          <p style="margin:0 0 8px;font-family:{FONT};font-size:14px;color:{MUTED};">
            This code expires in <strong style="color:{NAVY};">
            {OTP_EXPIRE_MINUTES} minutes</strong>.</p>
        </td></tr>
        <tr><td style="padding:16px 28px 28px;text-align:center;">
          <p style="margin:0;font-family:{FONT};font-size:12px;line-height:1.6;
                    color:{MUTED};border-top:1px solid #e3edf5;padding-top:16px;">
            {content["ignore"]} Never share this code with anyone.</p>
        </td></tr>
      </table>
      <p style="margin:16px 0 0;font-family:{FONT};font-size:12px;color:{MUTED};">
        &copy; ZamLine &middot; Freight coordination for Zambia</p>
    </td></tr>
  </table>
</body>
</html>"""


def sender_address() -> str:
    raw = EMAIL_FROM or EMAIL_USERNAME
    name, address = parseaddr(raw)
    if name or not address:
        return raw
    return formataddr((SENDER_NAME, address))


def build_otp_message(
    to_email: str, otp_code: str, content: dict = VERIFY
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender_address()
    message["To"] = to_email
    message["Subject"] = content["subject"].format(code=otp_code)
    message.set_content(build_otp_text(otp_code, content))
    message.add_alternative(build_otp_html(otp_code, content), subtype="html")
    return message


def _send(message: EmailMessage) -> None:
    if not (EMAIL_HOST and EMAIL_USERNAME and EMAIL_PASSWORD):
        raise RuntimeError("Email delivery is not configured")

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if EMAIL_USE_TLS:
            server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.send_message(message)


def send_otp_email(to_email: str, otp_code: str) -> None:
    _send(build_otp_message(to_email, otp_code, VERIFY))


def send_password_reset_email(to_email: str, otp_code: str) -> None:
    _send(build_otp_message(to_email, otp_code, RESET))
