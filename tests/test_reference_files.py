import json

import pytest

import services.reference_files as reference_files
from services.reference_files import (
    ReferenceFile,
    ReferenceFilesUnavailableError,
    citation_source_id,
    custom_metadata,
    describe_citations,
    known_citations,
    load_reference_files,
    source_register,
)


def reference_file(
    filename="DOC001_test.md",
    sha256="abc",
    content=b"# Reference",
):
    return ReferenceFile(
        filename=filename,
        sha256=sha256,
        content=content,
    )


def test_approved_reference_manifest_is_available():
    from config import GEMINI_REFERENCE_DIR

    manifest = json.loads(
        (GEMINI_REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8")
    )

    assert len(manifest) == 32
    assert all(entry["file"].endswith(".md") for entry in manifest)
    assert all(entry["id"] for entry in manifest)


def test_manifest_contains_no_legacy_retrieval_outputs():
    from config import GEMINI_REFERENCE_DIR

    manifest = json.loads(
        (GEMINI_REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8")
    )

    names = [entry["file"].lower() for entry in manifest]

    assert not any("chunk" in name for name in names)
    assert not any("bm25" in name for name in names)


def test_known_citations_come_from_reference_files():
    citations = known_citations()

    assert "[DOC018, p. 20]" in citations
    assert "[D02]" in citations
    assert "[D04]" in citations
    assert "[D05]" in citations
    assert "[D06]" in citations
    assert "[DOC999, p. 1]" not in citations


def test_source_register_reads_titles_and_urls():
    source = source_register()["DOC018"]

    assert source["title"] == "Time Release Study Report for Nakonde and Mwami Borders"
    assert source["publisher"] == "COMESA"
    assert source["url"].startswith("https://www.comesa.int/")


def test_describe_citations_skips_unknown_sources_and_duplicates():
    described = describe_citations(
        [
            "[DOC018, p. 20]",
            "[DOC018, p. 20]",
            "[D06]",
            "[DOC999, p. 1]",
        ]
    )

    assert [item["citation"] for item in described] == [
        "[DOC018, p. 20]",
        "[D06]",
    ]


def test_citation_source_id_reads_document_and_structured_ids():
    assert citation_source_id("[DOC018, p. 20]") == "DOC018"
    assert citation_source_id("[D06]") == "D06"
    assert citation_source_id("[DOC999, page twenty]") is None


def test_missing_reference_directory_is_reported(tmp_path):
    with pytest.raises(ReferenceFilesUnavailableError):
        load_reference_files.__wrapped__(tmp_path)


def test_manifest_controls_which_files_are_loaded(tmp_path):
    (tmp_path / "first.md").write_text(
        "# First",
        encoding="utf-8",
    )
    (tmp_path / "second.md").write_text(
        "# Second",
        encoding="utf-8",
    )
    (tmp_path / "ignored.md").write_text(
        "# Not approved",
        encoding="utf-8",
    )

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "file": "first.md",
                    "id": "DOC001",
                    "kind": "document",
                },
                {
                    "file": "second.md",
                    "id": "D02",
                    "kind": "structured summary",
                },
            ]
        ),
        encoding="utf-8",
    )

    files = load_reference_files.__wrapped__(tmp_path)

    assert [file.filename for file in files] == [
        "first.md",
        "second.md",
    ]


def test_missing_manifest_is_reported(tmp_path):
    with pytest.raises(ReferenceFilesUnavailableError):
        load_reference_files.__wrapped__(tmp_path)


def test_missing_manifest_file_is_reported(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "file": "missing.md",
                    "id": "DOC001",
                    "kind": "document",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReferenceFilesUnavailableError):
        load_reference_files.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "filename",
    [
        "../secret.md",
        "/tmp/secret.md",
        "nested/reference.md",
        "reference.txt",
    ],
)
def test_manifest_unsafe_paths_are_rejected(
    tmp_path,
    filename,
):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "file": filename,
                    "id": "DOC001",
                    "kind": "document",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReferenceFilesUnavailableError):
        load_reference_files.__wrapped__(tmp_path)


def test_custom_metadata_includes_stable_source_ids():
    metadata = custom_metadata(
        {
            "file": "DOC018_test.md",
            "id": "DOC018",
            "kind": "document",
            "publisher": "COMESA",
            "year": "2025",
            "geography": "Zambia",
        }
    )

    values = {item["key"]: item["string_value"] for item in metadata}

    assert values["source_ids"] == "DOC018"
    assert values["filename"] == "DOC018_test.md"
    assert values["publisher"] == "COMESA"


def test_file_search_sync_skips_unchanged_remote_document(
    monkeypatch,
):
    file = reference_file()
    previous = {
        "filename": file.filename,
        "sha256": file.sha256,
        "store": "fileSearchStores/test",
        "document_name": ("fileSearchStores/test/documents/doc1"),
        "status": "indexed",
    }

    saved = {}

    monkeypatch.setattr(
        reference_files,
        "load_reference_files",
        lambda: (file,),
    )
    monkeypatch.setattr(
        reference_files,
        "load_manifest",
        lambda: [
            {
                "file": file.filename,
                "id": "DOC001",
            }
        ],
    )
    monkeypatch.setattr(
        reference_files,
        "read_file_search_state",
        lambda: {file.filename: previous},
    )
    monkeypatch.setattr(
        reference_files,
        "write_file_search_state",
        saved.update,
    )
    monkeypatch.setattr(
        reference_files,
        "get_file_search_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        reference_files,
        "document_exists",
        lambda client, name: True,
    )

    result = reference_files.sync_reference_files_to_store(
        store_name="fileSearchStores/test"
    )

    assert result["indexed"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert saved[file.filename] == previous


def test_file_search_sync_indexes_changed_file(
    monkeypatch,
):
    file = reference_file(sha256="new-hash")

    state = {
        file.filename: {
            "filename": file.filename,
            "sha256": "old-hash",
            "store": "fileSearchStores/test",
            "document_name": ("fileSearchStores/test/documents/old"),
        }
    }

    saved = {}
    deleted = []

    monkeypatch.setattr(
        reference_files,
        "load_reference_files",
        lambda: (file,),
    )
    monkeypatch.setattr(
        reference_files,
        "load_manifest",
        lambda: [
            {
                "file": file.filename,
                "id": "DOC001",
            }
        ],
    )
    monkeypatch.setattr(
        reference_files,
        "read_file_search_state",
        lambda: state,
    )
    monkeypatch.setattr(
        reference_files,
        "write_file_search_state",
        saved.update,
    )
    monkeypatch.setattr(
        reference_files,
        "get_file_search_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        reference_files,
        "upload_reference_file",
        lambda client, store, item, entry: "fileSearchStores/test/documents/new",
    )
    monkeypatch.setattr(
        reference_files,
        "delete_document",
        lambda client, name: deleted.append(name),
    )

    result = reference_files.sync_reference_files_to_store(
        store_name="fileSearchStores/test"
    )

    assert result["indexed"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert deleted == ["fileSearchStores/test/documents/old"]
    assert saved[file.filename]["sha256"] == "new-hash"


def test_file_search_sync_removes_manifest_deleted_document(
    monkeypatch,
):
    removed_document = "fileSearchStores/test/documents/removed"
    deleted = []
    saved = {}

    monkeypatch.setattr(
        reference_files,
        "load_reference_files",
        lambda: (),
    )
    monkeypatch.setattr(
        reference_files,
        "load_manifest",
        lambda: [],
    )
    monkeypatch.setattr(
        reference_files,
        "read_file_search_state",
        lambda: {
            "removed.md": {
                "filename": "removed.md",
                "sha256": "old",
                "store": "fileSearchStores/test",
                "document_name": removed_document,
            }
        },
    )
    monkeypatch.setattr(
        reference_files,
        "write_file_search_state",
        saved.update,
    )
    monkeypatch.setattr(
        reference_files,
        "get_file_search_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        reference_files,
        "delete_document",
        lambda client, name: deleted.append(name),
    )

    result = reference_files.sync_reference_files_to_store(
        store_name="fileSearchStores/test"
    )

    assert result["removed"] == 1
    assert result["failed"] == 0
    assert deleted == [removed_document]
    assert saved == {}


def test_file_search_sync_reports_indexing_failure(
    monkeypatch,
):
    file = reference_file()

    monkeypatch.setattr(
        reference_files,
        "load_reference_files",
        lambda: (file,),
    )
    monkeypatch.setattr(
        reference_files,
        "load_manifest",
        lambda: [
            {
                "file": file.filename,
                "id": "DOC001",
            }
        ],
    )
    monkeypatch.setattr(
        reference_files,
        "read_file_search_state",
        lambda: {},
    )
    monkeypatch.setattr(
        reference_files,
        "write_file_search_state",
        lambda state: None,
    )
    monkeypatch.setattr(
        reference_files,
        "get_file_search_client",
        lambda: object(),
    )

    def fail_upload(
        client,
        store,
        item,
        entry,
    ):
        raise ReferenceFilesUnavailableError("indexing failed")

    monkeypatch.setattr(
        reference_files,
        "upload_reference_file",
        fail_upload,
    )

    result = reference_files.sync_reference_files_to_store(
        store_name="fileSearchStores/test"
    )

    assert result["indexed"] == 0
    assert result["failed"] == 1
    assert result["failures"][0]["file"] == file.filename


def test_reference_directory_resolves_inside_project():
    from config import GEMINI_REFERENCE_DIR, PROJECT_ROOT

    assert GEMINI_REFERENCE_DIR == PROJECT_ROOT / "reference_data"

    manifest_path = GEMINI_REFERENCE_DIR / "manifest.json"

    assert manifest_path.is_file()
    assert "/home/" not in manifest_path.read_text(encoding="utf-8")
