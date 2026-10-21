from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import models
from security.pacra_models import (
    CertificateProcessingUnavailable,
    OCRResult,
    QRScanResult,
)
from services.companies import (
    check_certificate_consistency,
    validate_company_fields,
)

PDF_BYTES = b"%PDF-1.4\n" + b"0" * 200
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 200


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch, tmp_path):
    folder = tmp_path / "certificates"
    monkeypatch.setattr("security.file_storage.UPLOAD_DIR", folder)
    return folder


def _certificate_text(name: str, registration: str) -> str:
    return (
        "REPUBLIC OF ZAMBIA\n"
        "Certificate of Incorporation\n"
        f"Company Name: {name}\n"
        f"Registration Number: {registration}\n"
    )


def _pdf_ocr(monkeypatch, text: str | None):
    result = (
        OCRResult(success=True, extracted_text=text)
        if text
        else OCRResult(success=False, error="No text found in PDF")
    )
    monkeypatch.setattr(
        "services.companies.PDFOCRProcessor.extract_text", lambda self, path: result
    )


def _upload(
    client, session, filename="cert.pdf", content=PDF_BYTES, mime="application/pdf"
):
    return client.post(
        f"/companies/{session['company_id']}/verify-certificate",
        headers=session["headers"],
        files={"certificate_file": (filename, content, mime)},
    )


def _set_status(db_session, company_id: str, new_status: models.VerificationStatus):
    company = db_session.get(models.Company, UUID(company_id))
    company.verification_status = new_status
    company.verified_at = (
        datetime.now(timezone.utc)
        if new_status == models.VerificationStatus.VERIFIED
        else None
    )
    db_session.commit()


def _audit_count(db_session, action_type: str) -> int:
    return db_session.query(models.AuditLog).filter_by(action_type=action_type).count()


class TestCreateCompany:
    def test_company_can_be_created(self, client, db_session):
        response = client.post(
            "/companies/create",
            json={
                "business_name": "  Zambia Freight  ",
                "registration_number": " 120180010448 ",
                "company_email": "Info@Zambia-Freight.com",
                "phone_number": "+260977000111",
                "company_type": "fleet",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["business_name"] == "Zambia Freight"
        assert body["registration_number"] == "120180010448"
        assert body["company_email"] == "info@zambia-freight.com"
        assert body["verification_status"] == "pending"
        assert _audit_count(db_session, "company_created") == 1

    def test_duplicate_email_and_registration_are_rejected(self, client):
        payload = {
            "business_name": "Zambia Freight",
            "registration_number": "120180010448",
            "company_email": "info@zambia-freight.com",
            "phone_number": "+260977000111",
            "company_type": "fleet",
        }
        assert client.post("/companies/create", json=payload).status_code == 201

        same_email = {**payload, "registration_number": "120199999999"}
        same_number = {**payload, "company_email": "other@zambia-freight.com"}

        assert client.post("/companies/create", json=same_email).status_code == 409
        assert client.post("/companies/create", json=same_number).status_code == 409

    def test_invalid_registration_number_is_rejected(self, client):
        response = client.post(
            "/companies/create",
            json={
                "business_name": "Zambia Freight",
                "registration_number": "no spaces!",
                "company_email": "info@zambia-freight.com",
                "phone_number": "+260977000111",
                "company_type": "fleet",
            },
        )
        assert response.status_code == 422


class TestCompanyAccess:
    def test_own_company_returns_the_full_profile(self, client, register_and_login):
        session = register_and_login("fleet")

        response = client.get(
            f"/companies/{session['company_id']}", headers=session["headers"]
        )

        assert response.status_code == 200
        body = response.json()
        assert body["registration_number"] == session["payload"]["registration_number"]
        assert body["phone_number"] == session["payload"]["phone_number"]
        assert "fuel_price_per_litre" in body

    def test_other_company_returns_only_a_summary(self, client, register_and_login):
        mine = register_and_login("shipper")
        theirs = register_and_login("fleet")

        response = client.get(
            f"/companies/{theirs['company_id']}", headers=mine["headers"]
        )

        assert response.status_code == 200
        assert set(response.json()) == {
            "company_id",
            "company_type",
            "business_name",
            "verification_status",
        }

    def test_unknown_and_malformed_ids_return_404(self, client, register_and_login):
        session = register_and_login()

        unknown = client.get(f"/companies/{uuid4()}", headers=session["headers"])
        malformed = client.get("/companies/not-a-uuid", headers=session["headers"])

        assert unknown.status_code == 404
        assert malformed.status_code == 404

    def test_requests_without_a_token_are_rejected(self, client, register_and_login):
        session = register_and_login()

        assert client.get("/companies/list").status_code == 401
        assert client.get(f"/companies/{session['company_id']}").status_code == 401
        assert client.delete(f"/companies/{session['company_id']}").status_code == 401

    def test_list_can_be_filtered_by_type(self, client, register_and_login):
        shipper = register_and_login("shipper")
        register_and_login("fleet")

        everything = client.get("/companies/list", headers=shipper["headers"])
        fleet_only = client.get(
            "/companies/list",
            params={"company_type": "fleet"},
            headers=shipper["headers"],
        )

        assert len(everything.json()) == 2
        assert [c["company_type"] for c in fleet_only.json()] == ["fleet"]

    def test_list_rejects_an_unknown_verification_status(
        self, client, register_and_login
    ):
        session = register_and_login()

        response = client.get(
            "/companies/list",
            params={"verification_status": "bogus"},
            headers=session["headers"],
        )

        assert response.status_code == 422


class TestUpdateCompany:
    @pytest.mark.parametrize("method", ["patch", "put"])
    def test_own_company_can_be_updated(self, client, register_and_login, method):
        session = register_and_login()

        response = getattr(client, method)(
            f"/companies/{session['company_id']}",
            headers=session["headers"],
            json={
                "business_name": "  New Name Ltd ",
                "phone_number": "+260 96 111 2222",
            },
        )

        assert response.status_code == 200
        assert response.json()["business_name"] == "New Name Ltd"
        assert response.json()["phone_number"] == "+260961112222"

    def test_another_company_cannot_be_updated(self, client, register_and_login):
        mine = register_and_login()
        theirs = register_and_login()

        response = client.patch(
            f"/companies/{theirs['company_id']}",
            headers=mine["headers"],
            json={"business_name": "Hijacked"},
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"business_name": "   "},
            {"business_name": "x" * 101},
            {"phone_number": "abc"},
            {"phone_number": "1" * 20},
        ],
    )
    def test_invalid_values_are_rejected(self, client, register_and_login, body):
        session = register_and_login()

        response = client.patch(
            f"/companies/{session['company_id']}", headers=session["headers"], json=body
        )

        assert response.status_code == 422

    def test_empty_update_changes_nothing_and_is_not_logged(
        self, client, db_session, register_and_login
    ):
        session = register_and_login()

        response = client.patch(
            f"/companies/{session['company_id']}", headers=session["headers"], json={}
        )

        assert response.status_code == 200
        assert _audit_count(db_session, "company_updated") == 0

    def test_renaming_a_verified_company_requires_reverification(
        self, client, db_session, register_and_login
    ):
        session = register_and_login()
        _set_status(
            db_session, session["company_id"], models.VerificationStatus.VERIFIED
        )

        response = client.patch(
            f"/companies/{session['company_id']}",
            headers=session["headers"],
            json={"business_name": "Completely Different Ltd"},
        )

        body = response.json()
        assert body["verification_status"] == "pending"
        assert body["verified_at"] is None
        assert "certificate" in body["verification_failure_reason"]

    def test_changing_only_the_phone_keeps_the_company_verified(
        self, client, db_session, register_and_login
    ):
        session = register_and_login()
        _set_status(
            db_session, session["company_id"], models.VerificationStatus.VERIFIED
        )

        response = client.patch(
            f"/companies/{session['company_id']}",
            headers=session["headers"],
            json={"phone_number": "+260961112222"},
        )

        assert response.json()["verification_status"] == "verified"


class TestCertificateVerification:
    def test_matching_certificate_verifies_the_company(
        self, client, db_session, register_and_login, monkeypatch
    ):
        session = register_and_login()
        payload = session["payload"]
        _pdf_ocr(
            monkeypatch,
            _certificate_text(payload["business_name"], payload["registration_number"]),
        )

        response = _upload(client, session)

        assert response.status_code == 200
        body = response.json()
        assert body["verified"] is True
        assert body["company"]["verification_status"] == "verified"
        assert body["company"]["verified_at"] is not None
        assert Path(body["certificate_file_url"]).exists()
        assert _audit_count(db_session, "verification_attempted") == 1

    def test_image_certificate_uses_both_qr_and_ocr(
        self, client, register_and_login, monkeypatch
    ):
        session = register_and_login()
        payload = session["payload"]
        monkeypatch.setattr(
            "services.companies.QRProcessor.scan",
            lambda self, path: QRScanResult(
                success=True, qr_data=f"PACRA {payload['registration_number']}"
            ),
        )
        monkeypatch.setattr(
            "services.companies.OCRProcessor.extract_text",
            lambda self, path: OCRResult(
                success=True, extracted_text=f"Company Name: {payload['business_name']}"
            ),
        )

        response = _upload(
            client, session, filename="cert.png", content=PNG_BYTES, mime="image/png"
        )

        assert response.status_code == 200
        assert response.json()["verified"] is True

    @pytest.mark.parametrize(
        ("certificate_name", "certificate_number", "expected_reason"),
        [
            ("Some Other Company", None, "business name"),
            (None, "REG999999", "registration number"),
            ("Some Other Company", "REG999999", "registration number"),
        ],
    )
    def test_mismatching_certificate_is_sent_back_for_resubmission(
        self,
        client,
        register_and_login,
        monkeypatch,
        certificate_name,
        certificate_number,
        expected_reason,
    ):
        session = register_and_login()
        payload = session["payload"]
        _pdf_ocr(
            monkeypatch,
            _certificate_text(
                certificate_name or payload["business_name"],
                certificate_number or payload["registration_number"],
            ),
        )

        response = _upload(client, session)

        body = response.json()
        assert response.status_code == 200
        assert body["verified"] is False
        assert body["company"]["verification_status"] == "resubmit"
        assert expected_reason in body["failure_reason"]

    def test_unreadable_certificate_is_sent_back_for_resubmission(
        self, client, register_and_login, monkeypatch
    ):
        session = register_and_login()
        _pdf_ocr(monkeypatch, None)

        response = _upload(client, session)

        assert response.json()["verified"] is False
        assert "could not be read" in response.json()["failure_reason"]

    def test_unavailable_tooling_returns_503_and_keeps_no_file(
        self, client, db_session, register_and_login, monkeypatch, upload_dir
    ):
        session = register_and_login()

        def _unavailable(self, path):
            raise CertificateProcessingUnavailable("tesseract missing")

        monkeypatch.setattr(
            "services.companies.PDFOCRProcessor.extract_text", _unavailable
        )

        response = _upload(client, session)

        assert response.status_code == 503
        assert list(upload_dir.glob("*")) == []
        company = db_session.get(models.Company, UUID(session["company_id"]))
        assert company.verification_status == models.VerificationStatus.PENDING

    def test_uploading_again_replaces_the_previous_file(
        self, client, register_and_login, monkeypatch, upload_dir
    ):
        session = register_and_login()
        _pdf_ocr(monkeypatch, None)

        _upload(client, session)
        _upload(client, session)

        assert len(list(upload_dir.glob("*"))) == 1

    @pytest.mark.parametrize(
        ("filename", "content", "mime"),
        [
            ("cert.txt", PDF_BYTES, "text/plain"),
            ("cert.exe", PDF_BYTES, "application/pdf"),
            ("cert.pdf", b"not a pdf at all" * 20, "application/pdf"),
            ("cert.pdf", b"%PDF-1.4", "application/pdf"),
            ("cert.png", PDF_BYTES, "image/png"),
        ],
    )
    def test_unsafe_uploads_are_rejected_before_storage(
        self, client, register_and_login, upload_dir, filename, content, mime
    ):
        session = register_and_login()

        response = _upload(client, session, filename, content, mime)

        assert response.status_code == 400
        assert list(upload_dir.glob("*")) == []

    def test_oversized_upload_is_rejected(self, client, register_and_login):
        session = register_and_login()
        content = b"%PDF-" + b"0" * (10 * 1024 * 1024)

        response = _upload(client, session, content=content)

        assert response.status_code == 413

    def test_another_company_cannot_upload_a_certificate(
        self, client, register_and_login, upload_dir
    ):
        mine = register_and_login()
        theirs = register_and_login()

        response = client.post(
            f"/companies/{theirs['company_id']}/verify-certificate",
            headers=mine["headers"],
            files={"certificate_file": ("cert.pdf", PDF_BYTES, "application/pdf")},
        )

        assert response.status_code == 403
        assert list(upload_dir.glob("*")) == []

    def test_retry_endpoint_behaves_like_the_first_attempt(
        self, client, register_and_login, monkeypatch
    ):
        session = register_and_login()
        payload = session["payload"]
        _pdf_ocr(
            monkeypatch,
            _certificate_text(payload["business_name"], payload["registration_number"]),
        )

        response = client.post(
            f"/companies/{session['company_id']}/verify-retry",
            headers=session["headers"],
            files={"certificate_file": ("cert.pdf", PDF_BYTES, "application/pdf")},
        )

        assert response.status_code == 200
        assert response.json()["verified"] is True


class TestCertificateRules:
    NAME = "Alpha Beta Logistics"
    NUMBER = "REG000001"

    def _check(self, text):
        return check_certificate_consistency(self.NAME, self.NUMBER, None, text)

    def test_exact_name_and_number_are_accepted(self):
        assert self._check(_certificate_text(self.NAME, self.NUMBER)).verified

    def test_case_and_punctuation_differences_are_tolerated(self):
        text = "company: ALPHA, BETA  logistics\nreg no. reg000001"
        assert self._check(text).verified

    def test_partially_matching_name_is_rejected(self):
        text = _certificate_text("Gamma Beta Logistics Ltd", self.NUMBER)
        assert not self._check(text).verified

    def test_number_hidden_inside_a_longer_token_is_rejected(self):
        outcome = self._check(_certificate_text(self.NAME, "REG0000012"))
        assert not outcome.verified

    def test_name_alone_is_not_enough(self):
        assert not self._check(f"Company Name: {self.NAME}").verified

    def test_number_alone_is_not_enough(self):
        assert not self._check(f"Registration Number: {self.NUMBER}").verified

    def test_either_source_may_supply_each_fact(self):
        outcome = check_certificate_consistency(
            self.NAME, self.NUMBER, f"PACRA {self.NUMBER}", f"Company: {self.NAME}"
        )
        assert outcome.verified
        assert outcome.extracted_registration == self.NUMBER

    def test_nothing_readable_is_sent_back(self):
        outcome = check_certificate_consistency(self.NAME, self.NUMBER, None, None)
        assert not outcome.verified
        assert outcome.status == "resubmit"


class TestCompanyFieldRules:
    def test_values_are_cleaned(self):
        cleaned = validate_company_fields(
            business_name="  Alpha   Beta ",
            registration_number=" 1201 8001 ",
            phone_number="+260 (97) 123-4567",
        )
        assert cleaned == {
            "business_name": "Alpha Beta",
            "registration_number": "12018001",
            "phone_number": "+260971234567",
        }

    def test_fields_that_were_not_given_are_left_out(self):
        assert validate_company_fields(phone_number="0971234567") == {
            "phone_number": "0971234567"
        }


class TestManualStatus:
    def test_company_can_move_itself_back_to_resubmit(self, client, register_and_login):
        session = register_and_login()

        response = client.post(
            f"/companies/{session['company_id']}/verify",
            headers=session["headers"],
            json={
                "verification_status": "resubmit",
                "verification_failure_reason": "  Scan was blurry ",
            },
        )

        assert response.status_code == 200
        assert response.json()["verification_status"] == "resubmit"
        assert response.json()["verification_failure_reason"] == "Scan was blurry"

    def test_company_can_never_mark_itself_verified(self, client, register_and_login):
        session = register_and_login()

        response = client.post(
            f"/companies/{session['company_id']}/verify",
            headers=session["headers"],
            json={"verification_status": "verified"},
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"verification_status": "bogus"},
            {
                "verification_status": "resubmit",
                "verification_failure_reason": "x" * 501,
            },
        ],
    )
    def test_invalid_status_requests_are_rejected(
        self, client, register_and_login, body
    ):
        session = register_and_login()

        response = client.post(
            f"/companies/{session['company_id']}/verify",
            headers=session["headers"],
            json=body,
        )

        assert response.status_code == 422

    def test_another_company_cannot_change_the_status(self, client, register_and_login):
        mine = register_and_login()
        theirs = register_and_login()

        response = client.post(
            f"/companies/{theirs['company_id']}/verify",
            headers=mine["headers"],
            json={"verification_status": "rejected"},
        )

        assert response.status_code == 403

    def test_status_endpoint_is_limited_to_the_own_company(
        self, client, register_and_login
    ):
        mine = register_and_login()
        theirs = register_and_login()

        own = client.get(
            f"/companies/{mine['company_id']}/verification-status",
            headers=mine["headers"],
        )
        other = client.get(
            f"/companies/{theirs['company_id']}/verification-status",
            headers=mine["headers"],
        )

        assert own.status_code == 200
        assert own.json()["verification_status"] == "pending"
        assert other.status_code == 403


class TestDeleteCompany:
    def test_another_company_cannot_be_deleted(self, client, register_and_login):
        mine = register_and_login()
        theirs = register_and_login()

        response = client.delete(
            f"/companies/{theirs['company_id']}", headers=mine["headers"]
        )

        assert response.status_code == 403

    def test_deletion_request_blocks_every_user_of_the_company(
        self, client, db_session, register_and_login
    ):
        session = register_and_login()

        response = client.delete(
            f"/companies/{session['company_id']}", headers=session["headers"]
        )

        assert response.status_code == 204
        assert client.get("/users/me", headers=session["headers"]).status_code == 401
        assert db_session.query(models.User).filter_by(is_active=True).count() == 0
        assert _audit_count(db_session, "company_deletion_requested") == 1
