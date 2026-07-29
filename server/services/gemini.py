"""Gemini API client — single-purpose wrapper around Google Generative AI SDK.

Handles: API calls, retries, timeout enforcement, response validation.
All nodes share this single client instance.
"""

from __future__ import annotations

import asyncio
import json as json_lib
import logging
from typing import Any

from google import genai
from google.genai import types

_logger = logging.getLogger(__name__)

# Known error patterns that warrant a retry
RETRYABLE_ERRORS = (
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
)

# Sane upper bound on any single backoff sleep, even if Gemini suggests longer.
MAX_BACKOFF_SECONDS = 60.0


class GeminiError(Exception):
    """Raised when Gemini returns a non-retryable error or max retries exhausted."""

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class _RetryableJsonParseError(GeminiError):
    """Internal marker: a JSON-parse failure that `generate()` should retry.

    Raised by `_extract_json` in place of a plain `GeminiError` so that the
    retry loop in `generate()` can distinguish "model returned malformed
    JSON" (retryable, within `max_retries`) from other `GeminiError`s such as
    an empty response (non-retryable). Still an instance of `GeminiError`, so
    any external code catching `GeminiError` continues to work unchanged.
    """


class GeminiClient:
    """Thin, focused wrapper around the Gemini SDK.

    Responsibilities:
    - Accept a prompt and return the generated text
    - Retry on transient failures (rate limits, timeouts)
    - Enforce per-call timeout
    - Parse JSON responses when requested

    Does NOT:
    - Know about template commands or resume structure
    - Hold any pipeline state
    - Interact with any other service
    """

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = "gemini-2.5-pro",
        fallback_model: str = "gemini-2.5-flash",
        timeout: float = 90.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._default_model = default_model
        self._fallback_model = fallback_model
        self._timeout = timeout

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        model: str | None = None,
        expect_json: bool = False,
        max_retries: int = 2,
    ) -> str:
        """Call Gemini and return the generated text.

        Args:
            prompt: The full prompt including system and user messages.
            temperature: 0.0–1.0 (lower = more deterministic).
            model: Model name (gemini-2.5-pro or gemini-2.5-flash).
            expect_json: If True, validate response is parseable JSON.
            max_retries: Number of retry attempts on transient errors.

        Returns:
            Generated text content.

        Raises:
            GeminiError: Non-retryable error or all retries exhausted.
        """
        last_error: Exception | None = None
        retry_status: str | None = None
        tried_fallback = False
        current_model = model or self._default_model

        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._client.models.generate_content,
                        model=current_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=temperature,
                        ),
                    ),
                    timeout=self._timeout,
                )

                text = (response.text or "").strip()
                if not text:
                    raise GeminiError("Gemini returned empty response")

                if expect_json:
                    text = self._extract_json(text)

                return text

            except asyncio.TimeoutError:
                last_error = GeminiError(
                    f"Gemini call timed out after {self._timeout}s",
                    status="DEADLINE_EXCEEDED",
                )
                retry_status = "DEADLINE_EXCEEDED"
                _logger.warning(
                    "Gemini call timed out (attempt %d/%d)", attempt + 1, max_retries + 1
                )

            except _RetryableJsonParseError as e:
                last_error = e
                retry_status = None
                _logger.warning(
                    "Gemini returned malformed JSON (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, e,
                )

            except GeminiError:
                raise  # Non-retryable

            except Exception as e:
                last_error = e
                retry_status = _extract_status(e)
                if retry_status not in RETRYABLE_ERRORS:
                    raise GeminiError(str(e), status=retry_status) from e

                # On 429 RESOURCE_EXHAUSTED or 503 UNAVAILABLE, switch to fallback model immediately
                if (retry_status in ("UNAVAILABLE", "RESOURCE_EXHAUSTED")) and not tried_fallback and self._fallback_model:
                    tried_fallback = True
                    _logger.info(
                        "Gemini %s %s — switching to fallback model %s (attempt %d/%d)",
                        current_model, retry_status, self._fallback_model, attempt + 1, max_retries + 1,
                    )
                    current_model = self._fallback_model
                    continue  # retry immediately with fallback model

                _logger.warning(
                    "Gemini retryable error %s (attempt %d/%d)",
                    retry_status, attempt + 1, max_retries + 1,
                )

            if attempt < max_retries:
                delay = _extract_retry_delay(last_error)
                backoff = delay if delay is not None else 2 ** attempt
                backoff = min(backoff, MAX_BACKOFF_SECONDS)
                _logger.info(
                    "Backing off %.1fs before retry %d%s",
                    backoff,
                    attempt + 1,
                    " (Gemini-suggested delay)" if delay is not None else "",
                )
                await asyncio.sleep(backoff)

        raise GeminiError(
            f"Gemini call failed after {max_retries + 1} attempts: {last_error}"
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences and validate JSON."""
        text = text.strip()
        if text.startswith("```"):
            newline = text.find("\n")
            text = text[newline + 1:] if newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            json_lib.loads(text)
        except json_lib.JSONDecodeError as exc:
            raise _RetryableJsonParseError(
                f"Gemini returned invalid JSON: {exc}"
            ) from exc
        return text


def _extract_retry_delay(exc: Exception) -> float | None:
    """Extract retryDelay from a 429 RESOURCE_EXHAUSTED error response.

    Google's API returns a RetryInfo protobuf with the recommended wait time.
    We parse the human-readable message for 'retry in Xs' or the retryDelay field.
    """
    import re
    exc_str = str(exc)
    # Pattern: "Please retry in 45.14619149s"
    m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", exc_str)
    if m:
        return float(m.group(1))
    # Pattern: "retryDelay': '45s'"
    m = re.search(r"retryDelay['\"]:\s*['\"](\d+)s", exc_str)
    if m:
        return float(m.group(1))
    return None


def _extract_status(exc: Exception) -> str | None:
    """Attempt to extract a gRPC status code from the exception chain."""
    exc_str = str(exc)
    for status in RETRYABLE_ERRORS + ("INVALID_ARGUMENT", "PERMISSION_DENIED"):
        if status in exc_str:
            return status
    return None


def _build_gemini_error(exc: Exception | None) -> GeminiError:
    if exc is None:
        return GeminiError("Unknown Gemini error")
    return GeminiError(str(exc))
