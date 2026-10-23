import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import errors, types

from config import (
    GEMINI_API_KEY,
    GEMINI_FILE_SEARCH_STATE_PATH,
    GEMINI_FILE_SEARCH_STORE,
    GEMINI_REFERENCE_DIR,
    GEMINI_TIMEOUT_SECONDS,
)
from services.errors import ExternalServiceError

MANIFEST_FILENAME = "manifest.json"
PAGE_HEADING_PATTERN = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
SOURCE_ID_PATTERN = re.compile(r"^\[(DOC\d{3}|D\d{2})(?:, p\. \d+)?\]$")
MANIFEST_SOURCE_ID_PATTERN = re.compile(r"DOC\d{3}|D\d{2}")
UPLOAD_MIME_TYPE = "text/markdown"
OPERATION_POLL_SECONDS = 2


class ReferenceFilesUnavailableError(ExternalServiceError):
    pass


@dataclass(frozen=True)
class ReferenceFile:
    filename: str
    sha256: str
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")


def load_manifest(directory: Path = GEMINI_REFERENCE_DIR) -> list[dict]:
    directory = Path(directory)
    manifest_path = directory / MANIFEST_FILENAME

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReferenceFilesUnavailableError(
            "Reference file manifest is not available or is invalid"
        ) from error

    if not isinstance(manifest, list) or not manifest:
        raise ReferenceFilesUnavailableError(
            "Reference file manifest must contain reference files"
        )

    validated = []
    seen = set()

    for entry in manifest:
        if not isinstance(entry, dict):
            raise ReferenceFilesUnavailableError(
                "Reference file manifest contains an invalid entry"
            )

        filename = entry.get("file")

        if not isinstance(filename, str) or not filename:
            raise ReferenceFilesUnavailableError(
                "Reference file manifest entry is missing a filename"
            )

        relative = Path(filename)

        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 1
            or relative.suffix.lower() != ".md"
        ):
            raise ReferenceFilesUnavailableError(
                "Reference file manifest contains an unsafe filename"
            )

        if filename in seen:
            raise ReferenceFilesUnavailableError(
                "Reference file manifest contains duplicate filenames"
            )

        seen.add(filename)
        validated.append(entry)

    return validated


def manifest_source_ids(entry: dict) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(MANIFEST_SOURCE_ID_PATTERN.findall(str(entry.get("id", ""))))
    )


@lru_cache
def load_reference_files(
    directory: Path = GEMINI_REFERENCE_DIR,
) -> tuple[ReferenceFile, ...]:
    directory = Path(directory)
    files = []

    for entry in load_manifest(directory):
        filename = entry["file"]
        file_path = directory / filename

        if not file_path.is_file():
            raise ReferenceFilesUnavailableError(
                f"Reference file is missing: {filename}"
            )

        content = file_path.read_bytes()

        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReferenceFilesUnavailableError(
                f"Reference file is not valid UTF-8: {filename}"
            ) from error

        files.append(
            ReferenceFile(
                filename=filename,
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        )

    return tuple(files)


@lru_cache
def known_citations(directory: Path = GEMINI_REFERENCE_DIR) -> frozenset[str]:
    citations = set()

    for entry in load_manifest(directory):
        source_ids = manifest_source_ids(entry)

        try:
            page_count = int(str(entry.get("pages", "")).strip())
        except (TypeError, ValueError):
            page_count = 0

        for source_id in source_ids:
            if source_id.startswith("DOC"):
                for page in range(1, page_count + 1):
                    citations.add(f"[{source_id}, p. {page}]")
            else:
                citations.add(f"[{source_id}]")

    return frozenset(citations)


@lru_cache
def source_register(
    directory: Path = GEMINI_REFERENCE_DIR,
) -> dict[str, dict]:
    register = {}

    for entry in load_manifest(directory):
        for source_id in manifest_source_ids(entry):
            register[source_id] = {
                "source_id": source_id,
                "title": entry.get("title", ""),
                "publisher": entry.get("publisher", ""),
                "date": entry.get("year", ""),
                "url": entry.get("source_url") or None,
                "geography": entry.get("geography", ""),
                "kind": entry.get("kind", ""),
            }

    return register


def citation_source_id(citation: str) -> str | None:
    match = SOURCE_ID_PATTERN.match(citation)
    return match.group(1) if match else None


def describe_citations(citations: list[str]) -> list[dict]:
    register = source_register()
    described = []

    for citation in dict.fromkeys(citations):
        source_id = citation_source_id(citation)
        source = register.get(source_id) if source_id else None

        if source:
            described.append(
                {
                    "citation": citation,
                    **source,
                }
            )

    return described


def read_file_search_state(
    path: Path | None = None,
) -> dict:
    state_path = Path(path or GEMINI_FILE_SEARCH_STATE_PATH)

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    return state if isinstance(state, dict) else {}


def write_file_search_state(
    state: dict,
    path: Path | None = None,
) -> None:
    state_path = Path(path or GEMINI_FILE_SEARCH_STATE_PATH)

    try:
        state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        state_path.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_file_search_client():
    if not GEMINI_API_KEY:
        raise ReferenceFilesUnavailableError("Gemini is not configured")

    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_SECONDS * 1000,
        ),
    )


def ensure_file_search_store(
    create_if_missing: bool = False,
) -> str:
    store = (GEMINI_FILE_SEARCH_STORE or "").strip()

    if store:
        return store

    if not create_if_missing:
        raise ReferenceFilesUnavailableError(
            "Gemini File Search store is not configured"
        )

    client = get_file_search_client()

    try:
        created = client.file_search_stores.create(
            config={
                "display_name": "ZamLine Freight References",
            }
        )
    except errors.APIError as error:
        raise ReferenceFilesUnavailableError(
            "Gemini File Search store could not be created"
        ) from error

    if not created.name:
        raise ReferenceFilesUnavailableError("Gemini File Search store was not created")

    return created.name


def custom_metadata(entry: dict) -> list[dict]:
    values = {
        "source_ids": ",".join(manifest_source_ids(entry)),
        "filename": entry.get("file", ""),
        "kind": entry.get("kind", ""),
        "publisher": entry.get("publisher", ""),
        "year": str(entry.get("year", "")),
        "geography": entry.get("geography", ""),
    }

    return [
        {
            "key": key,
            "string_value": str(value),
        }
        for key, value in values.items()
        if value not in (None, "")
    ]


def document_exists(client, document_name: str) -> bool:
    try:
        client.file_search_stores.documents.get(name=document_name)
        return True
    except errors.APIError as error:
        if getattr(error, "code", None) == 404:
            return False
        raise


def delete_document(client, document_name: str) -> None:
    try:
        client.file_search_stores.documents.delete(
            name=document_name,
            config={"force": True},
        )
    except errors.APIError as error:
        if getattr(error, "code", None) != 404:
            raise


def wait_for_operation(client, operation):
    while not operation.done:
        time.sleep(OPERATION_POLL_SECONDS)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise ReferenceFilesUnavailableError("Gemini File Search indexing failed")

    return operation


def upload_reference_file(
    client,
    store_name: str,
    file: ReferenceFile,
    entry: dict,
) -> str:
    path = GEMINI_REFERENCE_DIR / file.filename

    operation = client.file_search_stores.upload_to_file_search_store(
        file=str(path),
        file_search_store_name=store_name,
        config={
            "display_name": file.filename,
            "mime_type": UPLOAD_MIME_TYPE,
            "custom_metadata": custom_metadata(entry),
        },
    )

    operation = wait_for_operation(
        client,
        operation,
    )

    response = getattr(
        operation,
        "response",
        None,
    )

    document_name = getattr(
        response,
        "document_name",
        None,
    )

    if not document_name:
        raise ReferenceFilesUnavailableError(
            f"Gemini did not return an indexed document for {file.filename}"
        )

    return document_name


def sync_reference_files_to_store(
    store_name: str | None = None,
    *,
    force: bool = False,
    create_if_missing: bool = False,
) -> dict:
    store_name = (store_name or GEMINI_FILE_SEARCH_STORE or "").strip()

    if not store_name:
        store_name = ensure_file_search_store(create_if_missing=create_if_missing)

    client = get_file_search_client()
    manifest = load_manifest()
    files = load_reference_files()

    entries = {entry["file"]: entry for entry in manifest}

    state = read_file_search_state()
    current_names = {file.filename for file in files}

    active = {}
    indexed = 0
    skipped = 0
    removed = 0
    failures = []

    for file in files:
        previous = state.get(file.filename)

        reusable = (
            not force
            and isinstance(previous, dict)
            and previous.get("sha256") == file.sha256
            and previous.get("store") == store_name
            and isinstance(
                previous.get("document_name"),
                str,
            )
        )

        if reusable:
            try:
                reusable = document_exists(
                    client,
                    previous["document_name"],
                )
            except errors.APIError as error:
                failures.append(
                    {
                        "file": file.filename,
                        "error": str(error),
                    }
                )
                reusable = False

        if reusable:
            active[file.filename] = previous
            skipped += 1
            write_file_search_state(active)
            continue

        try:
            document_name = upload_reference_file(
                client,
                store_name,
                file,
                entries[file.filename],
            )
        except (
            errors.APIError,
            OSError,
            TimeoutError,
            ReferenceFilesUnavailableError,
        ) as error:
            failures.append(
                {
                    "file": file.filename,
                    "error": str(error),
                }
            )

            if isinstance(previous, dict):
                active[file.filename] = previous

            continue

        old_document = (
            previous.get("document_name") if isinstance(previous, dict) else None
        )

        if old_document and old_document != document_name:
            try:
                delete_document(
                    client,
                    old_document,
                )
            except errors.APIError:
                pass

        active[file.filename] = {
            "filename": file.filename,
            "sha256": file.sha256,
            "store": store_name,
            "document_name": document_name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "indexed",
        }

        indexed += 1
        write_file_search_state(active)

    for filename in sorted(set(state) - current_names):
        previous = state.get(filename)

        if not isinstance(previous, dict):
            continue

        document_name = previous.get("document_name")

        if not document_name:
            continue

        try:
            delete_document(
                client,
                document_name,
            )
            removed += 1
        except errors.APIError as error:
            active[filename] = previous
            failures.append(
                {
                    "file": filename,
                    "error": str(error),
                }
            )

    write_file_search_state(active)

    return {
        "store": store_name,
        "manifest_count": len(files),
        "indexed": indexed,
        "skipped": skipped,
        "removed": removed,
        "failed": len(failures),
        "failures": failures,
    }
