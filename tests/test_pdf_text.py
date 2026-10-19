from uuid import UUID

import pytest

import models
from security.pacra_models import OCRResult
from security.pacra_processor import read_pdf_text


def make_text_pdf(lines: list[str]) -> bytes:
    text_ops = "".join(
        f"BT /F1 12 Tf 50 {750 - 20 * index} Td ({line}) Tj ET\n"
        for index, line in enumerate(lines)
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(text_ops) + text_ops + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    output += b"startxref\n%d\n%%%%EOF\n" % xref
    return output


def certificate_pdf(name: str, registration: str) -> bytes:
    return make_text_pdf(
        [
            "REPUBLIC OF ZAMBIA",
            "Patents and Companies Registration Agency",
            "Certificate of Incorporation",
            f"Company Name: {name}",
            f"Registration Number: {registration}",
        ]
    )


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("security.file_storage.UPLOAD_DIR", tmp_path / "certs")


@pytest.fixture
def no_ocr_tools(monkeypatch):
    from pdf2image.exceptions import PDFInfoNotInstalledError

    def _missing(*args, **kwargs):
        raise PDFInfoNotInstalledError("poppler is not installed")

    monkeypatch.setattr("pdf2image.convert_from_path", _missing)


@pytest.fixture
def ocr_must_not_run(monkeypatch):
    def _fail(self, path):
        raise AssertionError("OCR should not run when the PDF text matches")

    monkeypatch.setattr("services.companies.PDFOCRProcessor.extract_text", _fail)


def ocr_returns(monkeypatch, text):
    monkeypatch.setattr(
        "services.companies.PDFOCRProcessor.extract_text",
        lambda self, path: OCRResult(success=True, extracted_text=text),
    )


class TestReadPdfText:
    def test_reads_text_from_a_text_pdf(self, tmp_path):
        path = tmp_path / "cert.pdf"
        path.write_bytes(certificate_pdf("Friends At Heart Foundation", "120180010448"))
        text = read_pdf_text(str(path))
        assert "Friends At Heart Foundation" in text
        assert "120180010448" in text

    def test_broken_pdf_gives_none(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4\n" + b"0" * 200)
        assert read_pdf_text(str(path)) is None

    def test_pdf_with_almost_no_text_gives_none(self, tmp_path):
        path = tmp_path / "scan.pdf"
        path.write_bytes(make_text_pdf(["Hi"]))
        assert read_pdf_text(str(path)) is None


class TestCertificateUploadWithTextPdf:
    def _upload(self, client, session, content):
        return client.post(
            f"/companies/{session['company_id']}/verify-certificate",
            headers=session["headers"],
            files={"certificate_file": ("pacra.pdf", content, "application/pdf")},
        )

    def _status(self, db_session, session):
        company = db_session.get(models.Company, UUID(session["company_id"]))
        db_session.refresh(company)
        return company

    def test_matching_certificate_is_verified(
        self, client, db_session, register_and_login, ocr_must_not_run
    ):
        session = register_and_login(
            "shipper",
            business_name="Friends At Heart Foundation",
            registration_number="120180010448",
        )
        pdf = certificate_pdf("Friends At Heart Foundation", "120180010448")
        response = self._upload(client, session, pdf)
        assert response.status_code == 200, response.text
        company = db_session.get(models.Company, UUID(session["company_id"]))
        db_session.refresh(company)
        assert company.verification_status == models.VerificationStatus.VERIFIED

    def test_wrong_name_and_number_fail_with_a_reason(
        self, client, db_session, register_and_login, no_ocr_tools
    ):
        session = register_and_login(
            "fleet",
            business_name="Friends At Heart Foundation",
            registration_number="120180010448",
        )
        pdf = certificate_pdf("Another Company Limited", "120111111111")
        response = self._upload(client, session, pdf)
        assert response.status_code == 200, response.text
        company = db_session.get(models.Company, UUID(session["company_id"]))
        db_session.refresh(company)
        assert company.verification_status == models.VerificationStatus.RESUBMIT
        assert "registration number" in company.verification_failure_reason
        assert "business name" in company.verification_failure_reason

    def test_ocr_is_tried_when_pdf_text_does_not_match(
        self, client, db_session, register_and_login, monkeypatch
    ):
        session = register_and_login(
            "shipper",
            business_name="Friends At Heart Foundation",
            registration_number="120180010448",
        )
        ocr_returns(
            monkeypatch,
            "Company Name: Friends At Heart Foundation\n"
            "Registration Number: 120180010448",
        )
        pdf = certificate_pdf("F r i e n d s  A t  H e a r t", "1 2 0 1 8")
        assert self._upload(client, session, pdf).status_code == 200
        company = self._status(db_session, session)
        assert company.verification_status == models.VerificationStatus.VERIFIED

    def test_scanned_pdf_without_ocr_tools_is_not_judged(
        self, client, db_session, register_and_login, no_ocr_tools
    ):
        session = register_and_login("shipper")
        scanned = make_text_pdf(["Hi"])
        response = self._upload(client, session, scanned)
        assert response.status_code == 503
        company = self._status(db_session, session)
        assert company.verification_status == models.VerificationStatus.PENDING
