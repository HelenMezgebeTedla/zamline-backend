import logging

from security.pacra_models import (
    CertificateProcessingUnavailable,
    OCRResult,
    QRScanResult,
)

logger = logging.getLogger(__name__)

OCR_TIMEOUT_SECONDS = 30


def _text_result(text: str | None, empty_error: str) -> OCRResult:
    if not text or not text.strip():
        return OCRResult(success=False, error=empty_error)
    return OCRResult(success=True, extracted_text=text.strip())


class QRProcessor:
    def scan(self, file_path: str) -> QRScanResult:
        try:
            from PIL import Image
            from pyzbar.pyzbar import decode
        except ImportError as exc:
            raise CertificateProcessingUnavailable(
                "QR scanning is unavailable"
            ) from exc

        try:
            with Image.open(file_path) as image:
                decoded = decode(image)
        except Exception as exc:
            logger.warning("QR scan failed: %s", type(exc).__name__)
            return QRScanResult(success=False, error="QR scan failed")

        if not decoded:
            return QRScanResult(success=False, error="No QR code found")
        try:
            qr_data = decoded[0].data.decode("utf-8")
        except UnicodeDecodeError:
            return QRScanResult(success=False, error="QR code is not readable text")
        return QRScanResult(success=True, qr_data=qr_data)


class OCRProcessor:
    def extract_text(self, file_path: str) -> OCRResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise CertificateProcessingUnavailable("OCR is unavailable") from exc

        try:
            with Image.open(file_path) as image:
                text = pytesseract.image_to_string(image, timeout=OCR_TIMEOUT_SECONDS)
        except pytesseract.TesseractNotFoundError as exc:
            raise CertificateProcessingUnavailable(
                "Tesseract is not installed"
            ) from exc
        except Exception as exc:
            logger.warning("OCR failed: %s", type(exc).__name__)
            return OCRResult(success=False, error="Text extraction failed")
        return _text_result(text, "No text found in image")


class PDFOCRProcessor:
    def extract_text(self, file_path: str) -> OCRResult:
        try:
            import pytesseract
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError
        except ImportError as exc:
            raise CertificateProcessingUnavailable("PDF OCR is unavailable") from exc

        try:
            pages = convert_from_path(
                file_path,
                first_page=1,
                last_page=1,
                timeout=OCR_TIMEOUT_SECONDS,
            )
            if not pages:
                return OCRResult(success=False, error="No pages found in PDF")
            text = pytesseract.image_to_string(pages[0], timeout=OCR_TIMEOUT_SECONDS)
        except (PDFInfoNotInstalledError, pytesseract.TesseractNotFoundError) as exc:
            raise CertificateProcessingUnavailable(
                "PDF tooling is not installed"
            ) from exc
        except Exception as exc:
            logger.warning("PDF OCR failed: %s", type(exc).__name__)
            return OCRResult(success=False, error="Text extraction failed")
        return _text_result(text, "No text found in PDF")
