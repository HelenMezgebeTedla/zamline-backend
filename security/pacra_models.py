from dataclasses import dataclass
from typing import Any


class CertificateProcessingUnavailable(Exception):
    pass


@dataclass
class QRScanResult:
    success: bool
    qr_data: str | None = None
    error: str | None = None
    raw_result: Any = None


@dataclass
class OCRResult:
    success: bool
    extracted_text: str | None = None
    error: str | None = None
    raw_result: Any = None
