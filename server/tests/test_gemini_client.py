"""Tests for GeminiClient retry/fallback model isolation.

Coverage:
- Property 1: model isolation across calls — a 429/503 fallback mid-call must
  never mutate `_default_model`, and later unrelated calls must still start
  on the original default model.

Constructing `GeminiClient` with a fake API key does not make a network
call (verified: `genai.Client(api_key=...)` only builds local HTTP options),
so real instances are constructed and `_client.models.generate_content` is
monkeypatched directly, mirroring the mocking style used in test_phase4.py /
test_phase5.py (mock at the boundary, exercise real logic otherwise).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from server.services.gemini import GeminiClient, GeminiError

DEFAULT_MODEL = "gemini-2.5-pro"
FALLBACK_MODEL = "gemini-2.5-flash"


def _make_client() -> GeminiClient:
    """Construct a real GeminiClient with a dummy key (no network call)."""
    return GeminiClient(
        api_key="fake-test-key",
        default_model=DEFAULT_MODEL,
        fallback_model=FALLBACK_MODEL,
    )


def _ok_response(text: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _retryable_error(status: str) -> Exception:
    """Build an exception whose string form embeds a retryable status code,
    matching how `_extract_status` scans `str(exc)` for known status names."""
    return Exception(f"429 {status}. Please retry in 0.01s")


class TestGeminiClientModelIsolation:
    """Property 1: Gemini client model isolation across calls.

    Validates: Requirements 3.1, 3.2, 3.3
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(
        retryable_status=st.sampled_from(["RESOURCE_EXHAUSTED", "UNAVAILABLE"]),
        temperature=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    async def test_default_model_unchanged_after_fallback_and_next_call_uses_it(
        self, retryable_status: str, temperature: float
    ) -> None:
        client = _make_client()
        model_before = client._default_model

        # First call: fails once with a retryable 429/503 (triggers a LOCAL
        # fallback to the flash model for this call only), then succeeds.
        first_call_models: list[str] = []

        def first_call_side_effect(*, model, contents, config):
            first_call_models.append(model)
            if len(first_call_models) == 1:
                raise _retryable_error(retryable_status)
            return _ok_response("first call recovered")

        client._client.models.generate_content = Mock(side_effect=first_call_side_effect)

        result_a = await client.generate(
            "prompt A", temperature=temperature, expect_json=False, max_retries=2
        )

        assert result_a == "first call recovered"
        # The call did fall back locally (second attempt used the fallback model).
        assert first_call_models[0] == model_before
        assert first_call_models[1] == FALLBACK_MODEL

        # Property: _default_model must be byte-identical to before this call.
        assert client._default_model == model_before

        # Second, unrelated call: succeeds immediately. It must start on the
        # original default model, not the fallback used during call A.
        second_call_models: list[str] = []

        def second_call_side_effect(*, model, contents, config):
            second_call_models.append(model)
            return _ok_response("second call ok")

        client._client.models.generate_content = Mock(side_effect=second_call_side_effect)

        result_b = await client.generate(
            "prompt B", temperature=temperature, expect_json=False, max_retries=2
        )

        assert result_b == "second call ok"
        assert second_call_models == [model_before]
        assert client._default_model == model_before


@pytest.mark.parametrize("retryable_status", ["RESOURCE_EXHAUSTED", "UNAVAILABLE"])
async def test_concrete_fallback_then_unrelated_call(retryable_status: str) -> None:
    """Concrete (non-hypothesis) scenario matching the design doc's example
    usage: a 429/503 fallback on call A must not affect call B's model."""
    client = _make_client()

    call_a_models: list[str] = []

    def call_a_side_effect(*, model, contents, config):
        call_a_models.append(model)
        if len(call_a_models) == 1:
            raise _retryable_error(retryable_status)
        return _ok_response("recovered")

    client._client.models.generate_content = Mock(side_effect=call_a_side_effect)
    text_a = await client.generate("prompt a", max_retries=2)

    assert text_a == "recovered"
    assert client._default_model == DEFAULT_MODEL

    call_b_models: list[str] = []
    client._client.models.generate_content = Mock(
        side_effect=lambda *, model, contents, config: (
            call_b_models.append(model) or _ok_response("b")
        )
    )
    text_b = await client.generate("prompt b", max_retries=2)

    assert text_b == "b"
    assert call_b_models == [DEFAULT_MODEL]
    assert client._default_model == DEFAULT_MODEL


class TestGeminiClientBackoffDelaySelection:
    """Property 2: Backoff delay uses parsed retry delay when available.

    Validates: Requirements 4.1, 4.2

    `INTERNAL` and `DEADLINE_EXCEEDED` are used as the retryable statuses
    here (rather than `UNAVAILABLE`/`RESOURCE_EXHAUSTED`) because those two
    never enter the fallback-model-switch branch in `generate()`, which
    `continue`s without sleeping on the first occurrence. That keeps these
    tests focused purely on the backoff-sleep-duration behavior.
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(delay=st.floats(min_value=0.1, max_value=200.0, allow_nan=False))
    async def test_sleep_uses_parsed_delay_capped_at_max(self, delay: float) -> None:
        """A retryable INTERNAL error whose message embeds a parseable
        'retry in Ns' delay must cause `asyncio.sleep` to be called with
        that parsed value, capped at MAX_BACKOFF_SECONDS (60.0)."""
        client = _make_client()
        # Format with fixed decimals so the regex-parsed value round-trips
        # exactly to what we assert against (avoids float repr / scientific
        # notation surprises for values in [0.1, 200.0]).
        delay_str = f"{delay:.4f}"
        expected_delay = float(delay_str)
        expected_backoff = min(expected_delay, 60.0)

        call_count = {"n": 0}

        def side_effect(*, model, contents, config):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception(f"500 INTERNAL. Please retry in {delay_str}s")
            return _ok_response("recovered")

        client._client.models.generate_content = Mock(side_effect=side_effect)

        with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await client.generate("prompt", expect_json=False, max_retries=2)

        assert result == "recovered"
        assert call_count["n"] == 2
        mock_sleep.assert_called_once()
        (actual_backoff,), _ = mock_sleep.call_args
        assert actual_backoff == pytest.approx(expected_backoff)

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(
        status=st.sampled_from(["INTERNAL", "DEADLINE_EXCEEDED"]),
        detail=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=15),
    )
    async def test_sleep_uses_exponential_fallback_when_no_parseable_delay(
        self, status: str, detail: str
    ) -> None:
        """A retryable error with no parseable delay pattern in its message
        must fall back to `2 ** attempt` for the sleep duration; on the
        first retry (attempt=0) that is `2 ** 0 == 1.0`."""
        client = _make_client()
        # `detail` is digit-free, so neither the 'retry in Ns' nor the
        # 'retryDelay': 'Ns'' regex (both require \d) can match.
        message = f"500 {status} {detail}"

        call_count = {"n": 0}

        def side_effect(*, model, contents, config):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception(message)
            return _ok_response("recovered")

        client._client.models.generate_content = Mock(side_effect=side_effect)

        with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await client.generate("prompt", expect_json=False, max_retries=2)

        assert result == "recovered"
        assert call_count["n"] == 2
        mock_sleep.assert_called_once()
        (actual_backoff,), _ = mock_sleep.call_args
        assert actual_backoff == pytest.approx(2 ** 0)


class TestGeminiClientJsonParseRetry:
    """Property 3: JSON parse failures are retried, not immediately fatal.

    Validates: Requirements 5.1, 5.2
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(
        n_early_failures=st.integers(min_value=0, max_value=1),
    )
    async def test_malformed_json_retried_until_valid(
        self, n_early_failures: int
    ) -> None:
        """With max_retries=2 (3 total attempts), malformed JSON on 0 or 1
        early attempts followed by valid JSON on the final attempt must
        succeed rather than raising on the first parse failure."""
        client = _make_client()

        valid_json_text = '{"key": "value"}'
        malformed_text = "this is not json at all {"

        call_texts: list[str] = []

        def side_effect(*, model, contents, config):
            call_texts.append(model)
            if len(call_texts) <= n_early_failures:
                return _ok_response(malformed_text)
            return _ok_response(valid_json_text)

        client._client.models.generate_content = Mock(side_effect=side_effect)

        with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()):
            result = await client.generate(
                "prompt", expect_json=True, max_retries=2
            )

        assert result == valid_json_text
        assert len(call_texts) == n_early_failures + 1


async def test_concrete_all_attempts_malformed_raises_after_exhaustion() -> None:
    """Concrete case: malformed JSON on every attempt (0, 1, 2 — 3 total
    with max_retries=2) must raise GeminiError only after all 3 attempts."""
    client = _make_client()
    malformed_text = "definitely not json"

    call_count = {"n": 0}

    def side_effect(*, model, contents, config):
        call_count["n"] += 1
        return _ok_response(malformed_text)

    client._client.models.generate_content = Mock(side_effect=side_effect)

    with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(GeminiError):
            await client.generate("prompt", expect_json=True, max_retries=2)

    assert call_count["n"] == 3


async def test_concrete_expect_json_false_skips_validation_and_retry() -> None:
    """Concrete case: expect_json=False with malformed-JSON-looking text must
    succeed immediately with no retry attempt, since _extract_json is only
    invoked when expect_json=True."""
    client = _make_client()
    response_text = "not json at all"

    call_count = {"n": 0}

    def side_effect(*, model, contents, config):
        call_count["n"] += 1
        return _ok_response(response_text)

    client._client.models.generate_content = Mock(side_effect=side_effect)

    with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        result = await client.generate("prompt", expect_json=False, max_retries=2)

    assert result == response_text
    assert call_count["n"] == 1
    mock_sleep.assert_not_called()


async def test_concrete_non_retryable_error_raises_immediately_without_retry() -> None:
    """Concrete case: a genuinely non-retryable status (INVALID_ARGUMENT) is
    on `_extract_status`'s scan list but NOT in `RETRYABLE_ERRORS`, so it
    must raise `GeminiError` immediately with no retry attempts at all —
    unlike retryable errors, which get up to `max_retries` additional tries.

    Validates: Requirements 3.1, 5.2
    """
    client = _make_client()

    call_count = {"n": 0}

    def side_effect(*, model, contents, config):
        call_count["n"] += 1
        raise Exception("400 INVALID_ARGUMENT: request contains an invalid argument")

    client._client.models.generate_content = Mock(side_effect=side_effect)

    with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(GeminiError):
            await client.generate("prompt", expect_json=False, max_retries=2)

    assert call_count["n"] == 1
    mock_sleep.assert_not_called()


async def test_concrete_empty_response_text_raises_gemini_error_without_retry() -> None:
    """Concrete case: an empty (or None) response text still raises
    `GeminiError("Gemini returned empty response")` as before — and since
    that raise happens via a bare `raise GeminiError(...)` inside the try
    block, it is caught by the `except GeminiError: raise` branch in the
    same method and propagates immediately without consuming a retry.

    Validates: Requirements 3.1, 5.2
    """
    client = _make_client()

    call_count = {"n": 0}

    def side_effect(*, model, contents, config):
        call_count["n"] += 1
        return _ok_response("")

    client._client.models.generate_content = Mock(side_effect=side_effect)

    with patch("server.services.gemini.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(GeminiError, match="Gemini returned empty response"):
            await client.generate("prompt", expect_json=False, max_retries=2)

    assert call_count["n"] == 1
    mock_sleep.assert_not_called()
