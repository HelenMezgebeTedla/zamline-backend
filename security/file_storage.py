import uuid
from pathlib import Path

from config import UPLOAD_DIR

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class FileStorage:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else Path(UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, original_name: str, content: bytes) -> str:
        extension = Path(original_name).suffix.lower()
        path = self.base_dir / f"{uuid.uuid4().hex}{extension}"
        path.write_bytes(content)
        return str(path)

    def read_file(self, file_path: str) -> bytes:
        return Path(file_path).read_bytes()

    def delete_file(self, file_path: str) -> None:
        Path(file_path).unlink(missing_ok=True)

    @staticmethod
    def get_file_content_type(file_path: str) -> str:
        return CONTENT_TYPES.get(
            Path(file_path).suffix.lower(), "application/octet-stream"
        )
