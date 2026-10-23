import json
import time
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import errors, types

from config import (
    GEMINI_API_KEY,
    GEMINI_FALLBACK_MODELS,
    GEMINI_FILE_SEARCH_STORE,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
)
from services.errors import ExternalServiceError

RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
ATTEMPTS_PER_MODEL = 2
RETRY_DELAY_SECONDS = 2


class GeminiUnavailableError(ExternalServiceError):
    pass


class GeminiRequestRejectedError(GeminiUnavailableError):
    pass


@dataclass(frozen=True)
class GeminiStructuredResult:
    data: dict
    grounded_source_ids: frozenset[str]
    grounding_contexts: tuple[dict, ...]


def candidate_models() -> list[str]:
    models = [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]
    return [
        model
        for index, model in enumerate(models)
        if model and model not in models[:index]
    ]


def build_client():
    if not GEMINI_API_KEY:
        raise GeminiUnavailableError("Gemini is not configured")

    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_SECONDS * 1000,
        ),
    )


def build_generation_config(
    instructions: str,
    response_schema: dict,
    file_search_store: str,
):
    return types.GenerateContentConfig(
        system_instruction=instructions,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=response_schema,
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=[file_search_store]
                )
            )
        ],
    )


def metadata_value(item):
    if getattr(item, "string_value", None) is not None:
        return item.string_value

    if getattr(item, "numeric_value", None) is not None:
        return item.numeric_value

    string_list = getattr(item, "string_list_value", None)
    if string_list is not None:
        return list(getattr(string_list, "values", None) or [])

    return None


def extract_grounding_contexts(response) -> tuple[dict, ...]:
    candidates = response.candidates or []
    if not candidates:
        return ()

    grounding = candidates[0].grounding_metadata
    if grounding is None:
        return ()

    contexts = []

    for chunk in grounding.grounding_chunks or []:
        retrieved = chunk.retrieved_context
        if retrieved is None:
            continue

        metadata = {}

        for item in retrieved.custom_metadata or []:
            if item.key:
                metadata[item.key] = metadata_value(item)

        contexts.append(
            {
                "title": retrieved.title,
                "uri": retrieved.uri,
                "text": retrieved.text,
                "page_number": retrieved.page_number,
                "file_search_store": retrieved.file_search_store,
                "metadata": metadata,
            }
        )

    return tuple(contexts)


def grounded_source_ids(contexts: tuple[dict, ...]) -> frozenset[str]:
    source_ids = set()

    for context in contexts:
        raw = context.get("metadata", {}).get("source_ids")

        if isinstance(raw, str):
            source_ids.update(
                value.strip() for value in raw.split(",") if value.strip()
            )

    return frozenset(source_ids)


def extract_result(response) -> GeminiStructuredResult:
    if not response.text:
        raise GeminiRequestRejectedError("Gemini returned an empty assessment")

    try:
        data = json.loads(response.text)
    except (TypeError, ValueError) as error:
        raise GeminiRequestRejectedError("Gemini returned invalid JSON") from error

    if not isinstance(data, dict):
        raise GeminiRequestRejectedError("Gemini returned an invalid assessment")

    contexts = extract_grounding_contexts(response)

    return GeminiStructuredResult(
        data=data,
        grounded_source_ids=grounded_source_ids(contexts),
        grounding_contexts=contexts,
    )


def call_model(
    client,
    model: str,
    instructions: str,
    context: dict,
    response_schema: dict,
    file_search_store: str,
) -> GeminiStructuredResult:
    response = client.models.generate_content(
        model=model,
        contents=json.dumps(context, default=str),
        config=build_generation_config(
            instructions,
            response_schema,
            file_search_store,
        ),
    )

    return extract_result(response)


def generate_structured_json(
    instructions: str,
    context: dict,
    response_schema: dict,
    file_search_store: str | None = None,
) -> GeminiStructuredResult:
    if not GEMINI_API_KEY or not GEMINI_MODEL:
        raise GeminiUnavailableError("Gemini is not configured")

    store = (file_search_store or GEMINI_FILE_SEARCH_STORE or "").strip()

    if not store:
        raise GeminiRequestRejectedError("Gemini File Search store is not configured")

    client = build_client()

    for model in candidate_models():
        for attempt in range(ATTEMPTS_PER_MODEL):
            try:
                return call_model(
                    client,
                    model,
                    instructions,
                    context,
                    response_schema,
                    store,
                )
            except GeminiRequestRejectedError:
                raise
            except errors.APIError as error:
                status = getattr(error, "code", None)

                if status not in RETRYABLE_STATUS_CODES:
                    raise GeminiRequestRejectedError(
                        "Gemini assessment failed"
                    ) from error

                if attempt + 1 < ATTEMPTS_PER_MODEL:
                    time.sleep(RETRY_DELAY_SECONDS)

            except (
                TimeoutError,
                httpx.TimeoutException,
                httpx.TransportError,
            ):
                if attempt + 1 < ATTEMPTS_PER_MODEL:
                    time.sleep(RETRY_DELAY_SECONDS)

    raise GeminiUnavailableError("Gemini is busy, try again shortly")
