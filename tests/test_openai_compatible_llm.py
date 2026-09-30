"""Tests for the OpenAI-compatible adapter."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest
import requests

from src.llm.errors import (
    LLMConnectionError,
    LLMGenerationLengthLimitError,
    LLMHealthCheckError,
    LLMRequestError,
    LLMTokenCountError,
    LLMTokenCountUnsupportedError,
)
from src.llm.openai_compatible_llm import OpenAICompatibleLLM


def _make_llm(**kwargs) -> OpenAICompatibleLLM:
    params = {
        "model_name": "local-model",
        "host": "http://127.0.0.1:1234",
        "timeout": 120,
        "retries": 3,
        "retry_delay": 0.0,
    }
    params.update(kwargs)
    return OpenAICompatibleLLM(
        **params,
    )


class _BlockingStreamResponse:
    def __init__(self, *, initial_content: str | None = None) -> None:
        self.ok = True
        self.encoding = "utf-8"
        self.initial_content = initial_content
        self.iterating = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()

    def iter_lines(self, **_kwargs):
        self.iterating.set()
        if self.initial_content is not None:
            event = {"choices": [{"delta": {"content": self.initial_content}}]}
            yield f"data: {json.dumps(event)}"
        assert self.closed.wait(timeout=2), "stream was not actively closed"
        raise requests.exceptions.ConnectionError("closed by cancellation")


class _ActiveAnswerlessStreamResponse:
    """Emit answerless SSE activity until the adapter closes the response."""

    def __init__(self, line: str = ": keepalive") -> None:
        self.ok = True
        self.encoding = "utf-8"
        self.line = line
        self.closed = threading.Event()
        self.iterating = threading.Event()
        self.close_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()

    def iter_lines(self, **_kwargs):
        self.iterating.set()
        while not self.closed.wait(0.005):
            yield self.line
        raise requests.exceptions.ConnectionError("closed by cancellation")


class _PostOutputInactiveStreamResponse(_ActiveAnswerlessStreamResponse):
    """Emit visible text once, then only non-answer SSE activity."""

    def iter_lines(self, **_kwargs):
        self.iterating.set()
        yield 'data: {"choices":[{"delta":{"content":"Partial answer"}}]}'
        metadata = [
            ": keepalive",
            "event: message",
            'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}',
            'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}',
        ]
        index = 0
        while not self.closed.wait(0.005):
            yield metadata[index % len(metadata)]
            index += 1
        raise requests.exceptions.ConnectionError("closed by cancellation")


def test_default_request_timeouts_use_short_connect_timeout():
    llm = _make_llm()
    assert llm.request_timeout == (10, 120)
    assert llm.stream_timeout == (10, None)


def test_get_uses_tuple_timeout_for_regular_requests():
    llm = _make_llm()
    mock_response = MagicMock()
    llm.session.get = MagicMock(return_value=mock_response)

    out = llm._get("/v1/models")

    assert out is mock_response
    call_kwargs = llm.session.get.call_args.kwargs
    assert call_kwargs["timeout"] == (10, 120)
    assert call_kwargs["allow_redirects"] is False


def test_health_check_is_fast_and_without_retries_by_default():
    llm = _make_llm(health_timeout=4, health_retries=0)
    llm.session.get = MagicMock(side_effect=requests.exceptions.ConnectTimeout("connect timeout"))

    with pytest.raises(LLMHealthCheckError):
        llm.health_check()

    assert llm.session.get.call_count == 1
    call_kwargs = llm.session.get.call_args.kwargs
    assert call_kwargs["timeout"] == (4, 4)


def test_health_check_does_not_report_managed_model_activity() -> None:
    events: list[str] = []
    llm = _make_llm(
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    response = MagicMock()
    response.raise_for_status.return_value = None
    llm.session.get = MagicMock(return_value=response)

    assert llm.health_check() is True
    assert events == []


def test_generate_stream_retries_on_model_crashed_runtime_error():
    llm = _make_llm(retries=1, retry_delay=0.0)

    # 1. Versuch: LM Studio meldet model crash (RuntimeError, retryable)
    first_ctx = MagicMock()
    first_ctx.__enter__.return_value = first_ctx
    first_ctx.__exit__.return_value = False
    first_ctx.ok = False
    first_ctx.status_code = 500
    first_ctx.text = "The model has crashed without additional information."
    first_ctx.json.return_value = {"error": {"message": first_ctx.text}}

    # 2. Versuch: erfolgreicher Stream
    second_ctx = MagicMock()
    second_ctx.__enter__.return_value = second_ctx
    second_ctx.__exit__.return_value = False
    second_ctx.ok = True
    second_ctx.encoding = "utf-8"
    second_ctx.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"Hallo"}}]}',
        "data: [DONE]",
    ]

    llm.session.post = MagicMock(side_effect=[first_ctx, second_ctx])

    chunks = list(llm.generate_stream("Test"))

    assert "".join(chunks) == "Hallo"
    assert llm.session.post.call_count == 2


def test_stream_request_activity_balances_on_completion() -> None:
    events: list[str] = []
    llm = _make_llm(
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()

    assert list(llm.generate_stream("Test", cancel_event=cancelled)) == ["ok"]
    assert events == ["active", "idle"]
    assert not any(
        thread.name == "aqa-llm-stream-cancellation" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_stream_request_activity_balances_when_consumer_closes() -> None:
    events: list[str] = []
    llm = _make_llm(
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = iter(
        [
            'data: {"choices":[{"delta":{"content":"first"}}]}',
            'data: {"choices":[{"delta":{"content":"second"}}]}',
        ]
    )
    llm.session.post = MagicMock(return_value=response)

    stream = llm.generate_stream("Test")
    assert next(stream) == "first"
    stream.close()

    assert events == ["active", "idle"]
    response.__exit__.assert_called_once()


def test_cancellation_closes_stream_blocked_before_first_event_with_bounded_latency() -> None:
    events: list[str] = []
    llm = _make_llm(
        retries=3,
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    response = _BlockingStreamResponse()
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()
    result: list[str] = []
    failures: list[BaseException] = []

    def consume() -> None:
        try:
            result.extend(llm.generate_stream("Test", cancel_event=cancelled))
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    assert response.iterating.wait(timeout=1)
    started = time.monotonic()
    cancelled.set()
    worker.join(timeout=0.5)

    assert not worker.is_alive()
    assert time.monotonic() - started < 0.5
    assert response.close_calls == 1
    assert result == []
    assert failures == []
    assert events == ["active", "idle"]
    assert llm.session.post.call_count == 1
    assert "cancel_event" not in llm.session.post.call_args.kwargs["json"]


def test_cancellation_after_partial_content_closes_without_retry_or_duplicate() -> None:
    llm = _make_llm(retries=3)
    response = _BlockingStreamResponse(initial_content="kept")
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()
    result: list[str] = []
    worker = threading.Thread(
        target=lambda: result.extend(llm.generate_stream("Test", cancel_event=cancelled))
    )

    worker.start()
    assert response.iterating.wait(timeout=1)
    while not result:
        time.sleep(0.005)
    cancelled.set()
    worker.join(timeout=0.5)

    assert not worker.is_alive()
    assert result == ["kept"]
    assert response.close_calls == 1
    assert llm.session.post.call_count == 1


def test_cancellation_closes_only_the_response_owned_by_that_request() -> None:
    llm = _make_llm(retries=0)
    first = _BlockingStreamResponse()
    second = _BlockingStreamResponse()
    llm.session.post = MagicMock(side_effect=[first, second])
    first_cancelled = threading.Event()
    second_cancelled = threading.Event()
    first_worker = threading.Thread(
        target=lambda: list(llm.generate_stream("First", cancel_event=first_cancelled))
    )
    second_worker = threading.Thread(
        target=lambda: list(llm.generate_stream("Second", cancel_event=second_cancelled))
    )

    first_worker.start()
    assert first.iterating.wait(timeout=1)
    second_worker.start()
    assert second.iterating.wait(timeout=1)
    first_cancelled.set()
    first_worker.join(timeout=0.5)

    assert not first_worker.is_alive()
    assert first.close_calls == 1
    assert second.close_calls == 0
    assert second_worker.is_alive()

    second_cancelled.set()
    second_worker.join(timeout=0.5)
    assert not second_worker.is_alive()


def test_stream_close_aborts_blocked_http_response_and_releases_worker() -> None:
    llm = _make_llm(retries=3)
    entered = threading.Event()
    response_closed = threading.Event()
    worker_done = threading.Event()

    class BlockingResponse:
        ok = True
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def iter_lines(self, decode_unicode=True):
            assert decode_unicode is True
            entered.set()
            response_closed.wait()
            return iter(())

        def close(self):
            response_closed.set()

    llm.session.post = MagicMock(return_value=BlockingResponse())
    stream = llm.generate_stream("Test")
    errors: list[Exception] = []

    def consume() -> None:
        try:
            list(stream)
        except Exception as exc:
            errors.append(exc)
        finally:
            worker_done.set()

    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    assert entered.wait(timeout=1)

    stream.close()

    assert response_closed.wait(timeout=1)
    assert worker_done.wait(timeout=1)
    assert errors == []
    assert llm.session.post.call_count == 1


def test_stream_request_activity_balances_on_provider_error() -> None:
    events: list[str] = []
    llm = _make_llm(
        retries=0,
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = False
    response.status_code = 500
    response.text = "failed"
    response.json.return_value = {"error": {"message": "failed"}}
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError):
        list(llm.generate_stream("Test"))

    assert events == ["active", "idle"]


def test_request_activity_observer_failures_do_not_break_provider_request() -> None:
    def observer_failure() -> None:
        raise RuntimeError("observer unavailable")

    llm = _make_llm(
        request_started=observer_failure,
        request_finished=observer_failure,
    )
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    llm.session.post = MagicMock(return_value=response)

    assert llm.generate("Test") == "ok"


def test_generate_stream_enables_thinking_and_omits_reasoning_from_yielded_text():
    llm = _make_llm(enable_thinking=True)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"reasoning_content":"internal reasoning"}}]}',
        'data: {"choices":[{"delta":{"content":"Final answer"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    chunks = list(llm.generate_stream("Test"))

    assert chunks == ["Final answer"]
    payload = llm.session.post.call_args.kwargs["json"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


def test_generate_stream_accepts_silent_inference_past_former_deadline():
    llm = _make_llm(retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    simulated_elapsed = 0

    def delayed_lines(**_kwargs):
        nonlocal simulated_elapsed
        simulated_elapsed = 601
        yield 'data: {"choices":[{"delta":{"content":"Answer"}}]}'
        yield "data: [DONE]"

    response.iter_lines.side_effect = delayed_lines
    llm.session.post = MagicMock(return_value=response)

    assert list(llm.generate_stream("Test")) == ["Answer"]
    assert simulated_elapsed > 600
    assert llm.session.post.call_count == 1
    assert llm.session.post.call_args.kwargs["timeout"] == (10, None)


def test_generate_stream_accepts_extended_heartbeats_and_reasoning_before_success():
    llm = _make_llm(retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.iter_lines.return_value = [
        ": keepalive",
        "event: message",
        'data: {"choices":[{"delta":{"reasoning_content":"still thinking"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":0,"total_tokens":1}}',
        'data: {"choices":[{"delta":{"content":"Answer"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    assert list(llm.generate_stream("Test")) == ["Answer"]
    assert llm.session.post.call_args.kwargs["timeout"] == (10, None)


@pytest.mark.parametrize(
    "answerless_line",
    [
        ": keepalive",
        "event: message",
        'data: {"choices":[{"delta":{"reasoning_content":"still thinking"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":0,"total_tokens":1}}',
    ],
)
def test_cancellation_during_answerless_activity_never_replays(answerless_line):
    llm = _make_llm(retries=3, retry_delay=0.0)
    response = _ActiveAnswerlessStreamResponse(answerless_line)
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()
    result: list[str] = []
    failures: list[BaseException] = []

    def consume() -> None:
        try:
            result.extend(llm.generate_stream("Test", cancel_event=cancelled))
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    assert response.iterating.wait(timeout=1)
    cancelled.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == []
    assert failures == []
    assert response.close_calls == 1
    assert llm.session.post.call_count == 1


def test_visible_output_then_metadata_remains_pending_until_cancel_without_replay():
    llm = _make_llm(retries=3, retry_delay=0.0)
    response = _PostOutputInactiveStreamResponse()
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()
    result: list[str] = []
    failures: list[BaseException] = []

    def consume() -> None:
        try:
            result.extend(llm.generate_stream("Test", cancel_event=cancelled))
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    assert response.iterating.wait(timeout=1)
    while result != ["Partial answer"]:
        time.sleep(0.005)
    cancelled.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == ["Partial answer"]
    assert failures == []
    assert response.close_calls == 1
    assert llm.session.post.call_count == 1


def test_cancellation_during_answerless_wait_remains_cancellation():
    llm = _make_llm(retries=3)
    response = _BlockingStreamResponse()
    llm.session.post = MagicMock(return_value=response)
    cancelled = threading.Event()
    result: list[str] = []
    failures: list[BaseException] = []

    def consume() -> None:
        try:
            result.extend(llm.generate_stream("Test", cancel_event=cancelled))
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    assert response.iterating.wait(timeout=1)
    cancelled.set()
    worker.join(timeout=0.5)

    assert not worker.is_alive()
    assert result == []
    assert failures == []
    assert llm.session.post.call_count == 1


def test_cancellation_interrupts_a_real_silent_socket_and_cleans_up():
    headers_flushed = threading.Event()
    peer_closed = threading.Event()

    class SilentSSEHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            return

        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            headers_flushed.set()
            try:
                self.connection.settimeout(3)
                if self.connection.recv(1) == b"":
                    peer_closed.set()
            except (OSError, TimeoutError):
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SilentSSEHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    events: list[str] = []
    llm = OpenAICompatibleLLM(
        model_name="synthetic-model",
        host=f"http://127.0.0.1:{server.server_port}",
        connect_timeout=1,
        stream_timeout=None,
        retries=0,
        request_started=lambda: events.append("active"),
        request_finished=lambda: events.append("idle"),
    )
    cancelled = threading.Event()
    result: list[str] = []
    failures: list[BaseException] = []
    stream = llm.generate_stream("Test", cancel_event=cancelled)

    def consume() -> None:
        try:
            result.extend(stream)
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        assert headers_flushed.wait(timeout=2)
        cancelled.set()
        worker.join(timeout=2)
        assert peer_closed.wait(timeout=2)

        assert not worker.is_alive()
        assert result == []
        assert failures == []
        assert events == ["active", "idle"]
        assert stream._response is None
        assert not any(
            thread.name == "aqa-llm-stream-cancellation" and thread.is_alive()
            for thread in threading.enumerate()
        )
    finally:
        stream.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_generate_stream_keeps_final_text_before_length_limit_error():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"Teil"},"finish_reason":"length"}]}',
    ]
    llm.session.post = MagicMock(return_value=response)

    stream = llm.generate_stream("Test")
    assert next(stream) == "Teil"
    with pytest.raises(LLMGenerationLengthLimitError):
        next(stream)
    assert llm.session.post.call_count == 1


def test_length_limit_before_visible_output_is_not_retried():
    llm = _make_llm(retries=3)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMGenerationLengthLimitError):
        list(llm.generate_stream("Test"))

    assert llm.session.post.call_count == 1


def test_first_visible_output_preserves_partial_disconnect_without_replay():
    llm = _make_llm(retries=3, retry_delay=0.0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True

    def lines(**_kwargs):
        yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
        raise requests.exceptions.ConnectionError("provider disconnected")

    response.iter_lines.side_effect = lines
    llm.session.post = MagicMock(return_value=response)
    stream = llm.generate_stream("Test")

    assert next(stream) == "partial"
    with pytest.raises(LLMConnectionError) as exc_info:
        next(stream)

    assert exc_info.value.code == "provider_connection_failed"
    assert llm.session.post.call_count == 1


def test_generate_stream_requests_and_reports_final_openai_usage():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"Hallo"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)
    usages = []

    assert list(llm.generate_stream("Test", on_usage=usages.append)) == ["Hallo"]
    assert usages == [{"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}]
    assert llm.session.post.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}
    assert llm.session.post.call_args.kwargs["allow_redirects"] is False


def test_generate_stream_accepts_data_field_without_optional_space_and_sse_metadata():
    llm = _make_llm(retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.iter_lines.return_value = [
        ": keepalive",
        "event: message",
        'data:{"choices":[{"delta":{"content":"Hallo"},"finish_reason":"stop"}]}',
    ]
    llm.session.post = MagicMock(return_value=response)

    assert list(llm.generate_stream("Test")) == ["Hallo"]


def test_generate_stream_rejects_malformed_data_event():
    llm = _make_llm(retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.iter_lines.return_value = ["data: {not-json}"]
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))

    assert exc_info.value.code == "provider_response_invalid"


def test_generate_stream_retries_premature_eof_only_before_output():
    llm = _make_llm(retries=1, retry_delay=0.0)
    incomplete = MagicMock()
    incomplete.__enter__.return_value = incomplete
    incomplete.__exit__.return_value = False
    incomplete.ok = True
    incomplete.iter_lines.return_value = [
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":0,"total_tokens":1}}'
    ]
    recovered = MagicMock()
    recovered.__enter__.return_value = recovered
    recovered.__exit__.return_value = False
    recovered.ok = True
    recovered.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(side_effect=[incomplete, recovered])

    assert list(llm.generate_stream("Test")) == ["ok"]
    assert llm.session.post.call_count == 2


def test_generate_stream_does_not_retry_premature_eof_after_output():
    llm = _make_llm(retries=2, retry_delay=0.0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.iter_lines.return_value = ['data: {"choices":[{"delta":{"content":"partial"}}]}']
    llm.session.post = MagicMock(return_value=response)

    stream = llm.generate_stream("Test")
    assert next(stream) == "partial"
    with pytest.raises(LLMRequestError) as exc_info:
        next(stream)

    assert exc_info.value.code == "provider_stream_incomplete"
    assert llm.session.post.call_count == 1


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 0},
        {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": "1", "total_tokens": 2},
        {"prompt_tokens": 1, "completion_tokens": 1},
    ],
)
def test_generate_stream_ignores_invalid_usage_values(usage):
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        f'data: {{"usage":{json.dumps(usage)},"choices":[{{"delta":{{"content":"ok"}}}}]}}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)
    usages = []

    assert list(llm.generate_stream("Test", on_usage=usages.append)) == ["ok"]
    assert usages == []


def test_generate_stream_accepts_zero_usage_values():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0},"choices":[]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)
    usages = []

    assert list(llm.generate_stream("Test", on_usage=usages.append)) == []
    assert usages == [{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}]


def test_generate_stream_reads_usage_after_length_finish_reason():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"Teil"},"finish_reason":"length"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":1,"total_tokens":10}}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)
    usages = []

    stream = llm.generate_stream("Test", on_usage=usages.append)
    assert next(stream) == "Teil"
    with pytest.raises(LLMGenerationLengthLimitError):
        next(stream)
    assert usages == [{"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10}]


def test_generate_stream_retries_once_without_stream_options_when_rejected():
    llm = _make_llm(retries=0)
    rejected = MagicMock()
    rejected.__enter__.return_value = rejected
    rejected.__exit__.return_value = False
    rejected.ok = False
    rejected.status_code = 400
    rejected.text = "unknown parameter stream_options.include_usage"
    rejected.json.return_value = {"error": {"message": rejected.text}}
    accepted = MagicMock()
    accepted.__enter__.return_value = accepted
    accepted.__exit__.return_value = False
    accepted.ok = True
    accepted.encoding = "utf-8"
    accepted.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(side_effect=[rejected, accepted])

    assert list(llm.generate_stream("Test")) == ["ok"]
    assert llm.session.post.call_count == 2
    assert "stream_options" in llm.session.post.call_args_list[0].kwargs["json"]
    assert "stream_options" not in llm.session.post.call_args_list[1].kwargs["json"]


def test_generate_stream_does_not_retry_other_client_errors_without_text():
    llm = _make_llm(retries=0)
    rejected = MagicMock()
    rejected.__enter__.return_value = rejected
    rejected.__exit__.return_value = False
    rejected.ok = False
    rejected.status_code = 400
    rejected.text = "invalid model"
    rejected.json.return_value = {"error": {"message": rejected.text}}
    llm.session.post = MagicMock(return_value=rejected)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))
    assert llm.session.post.call_count == 1
    assert exc_info.value.code == "provider_model_rejected"
    assert "LM Studio" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("status", "detail", "code"),
    [
        (401, "invalid API key", "provider_authentication_failed"),
        (402, "insufficient credits", "provider_credit_required"),
        (429, "rate limit exceeded", "provider_rate_limited"),
        (504, "upstream timeout", "provider_timeout"),
        (503, "provider unavailable", "provider_unavailable"),
    ],
)
def test_generate_stream_classifies_provider_http_errors(status, detail, code):
    llm = _make_llm(retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = False
    response.status_code = status
    response.text = detail
    response.json.return_value = {"error": {"message": detail}}
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))

    assert exc_info.value.code == code
    assert str(exc_info.value) == f"HTTP {status}: {detail}"
    assert "LM Studio" not in str(exc_info.value)


@pytest.mark.parametrize("provider_error", ["plain failure", ["nested", "failure"], {}])
def test_generate_stream_accepts_non_object_provider_error_shapes(provider_error):
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        f"data: {json.dumps({'error': provider_error})}",
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError):
        list(llm.generate_stream("Test"))


def test_generate_stream_classifies_in_band_provider_error():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"error":{"message":"insufficient credits","code":402}}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))

    assert exc_info.value.code == "provider_credit_required"


@pytest.mark.parametrize(
    "detail",
    [
        "Authorization: Bearer aqa-test-secret-123 rejected",
        "api_key=aqa-test-secret-123 is invalid",
        "request failed?access_token=aqa-test-secret-123&retry=1",
    ],
)
def test_provider_http_errors_redact_credentials(detail):
    secret = "aqa-test-secret-123"
    llm = _make_llm(api_key=secret, retries=0)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = False
    response.status_code = 401
    response.text = detail
    response.json.return_value = {"error": {"message": detail}}
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))

    assert exc_info.value.code == "provider_authentication_failed"
    assert secret not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_in_band_provider_errors_redact_configured_key():
    secret = "aqa-test-secret-in-band"
    llm = _make_llm(api_key=secret)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        f'data: {{"error":{{"message":"Bearer {secret} was rejected"}}}}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    with pytest.raises(LLMRequestError) as exc_info:
        list(llm.generate_stream("Test"))

    assert secret not in str(exc_info.value)
    assert "Bearer [REDACTED]" in str(exc_info.value)


def test_partial_stream_transport_failure_is_classified_without_retry_or_secret_leak():
    secret = "aqa-test-secret-partial"
    llm = _make_llm(api_key=secret, retries=3)
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"

    def failing_lines(**_kwargs):
        yield 'data: {"choices":[{"delta":{"content":"Kept"}}]}'
        raise requests.exceptions.ReadTimeout(f"Bearer {secret} timed out")

    response.iter_lines = failing_lines
    llm.session.post = MagicMock(return_value=response)

    stream = llm.generate_stream("Test")
    assert next(stream) == "Kept"
    with pytest.raises(LLMConnectionError) as exc_info:
        next(stream)

    assert exc_info.value.code == "provider_timeout"
    assert secret not in str(exc_info.value)
    assert "Bearer [REDACTED]" in str(exc_info.value)
    assert llm.session.post.call_count == 1


def test_generate_stream_retries_provider_unavailable_before_output():
    llm = _make_llm(retries=1)
    unavailable = MagicMock()
    unavailable.__enter__.return_value = unavailable
    unavailable.__exit__.return_value = False
    unavailable.ok = False
    unavailable.status_code = 503
    unavailable.text = "overloaded"
    unavailable.json.return_value = {"error": {"message": "overloaded"}}
    completed = MagicMock()
    completed.__enter__.return_value = completed
    completed.__exit__.return_value = False
    completed.ok = True
    completed.encoding = "utf-8"
    completed.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"Recovered"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(side_effect=[unavailable, completed])

    assert list(llm.generate_stream("Test")) == ["Recovered"]
    assert llm.session.post.call_count == 2


def test_generate_enables_thinking_and_returns_only_final_content():
    llm = _make_llm(enable_thinking=True)
    response = MagicMock()
    response.json.return_value = {
        "choices": [
            {"message": {"reasoning_content": "internal reasoning", "content": "Final answer"}}
        ]
    }
    llm._post = MagicMock(return_value=response)

    result = llm.generate("Test")

    assert result == "Final answer"
    payload = llm._post.call_args.args[1]
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


def test_custom_model_id_is_sent_to_generation_unchanged():
    custom_model = "@preset/deployment-alias"
    llm = _make_llm(model_name=custom_model)
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    llm._post = MagicMock(return_value=response)

    assert llm.generate("Test") == "ok"

    assert llm._post.call_args.args[1]["model"] == custom_model


def test_get_raises_llm_connection_error_after_retries():
    llm = _make_llm(retries=1, retry_delay=0.0)
    llm.session.get = MagicMock(side_effect=requests.exceptions.ConnectTimeout("connect timeout"))

    with pytest.raises(LLMConnectionError):
        llm._get("/v1/models")

    assert llm.session.get.call_count == 2


# Temperature: omit when None, include when explicit
def test_generate_omits_temperature_when_none():
    llm = _make_llm()
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    llm._post = MagicMock(return_value=response)

    llm.generate("Test", temperature=None)

    payload = llm._post.call_args.args[1]
    assert "temperature" not in payload, (
        "temperature=None must be omitted from the JSON payload so the "
        "provider can use its own default"
    )


def test_generate_includes_explicit_numeric_temperature():
    llm = _make_llm()
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    llm._post = MagicMock(return_value=response)

    llm.generate("Test", temperature=1.0)

    payload = llm._post.call_args.args[1]
    assert payload["temperature"] == 1.0


def test_generate_stream_omits_temperature_when_none():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"x"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    chunks = list(llm.generate_stream("Test", temperature=None))
    assert "".join(chunks) == "x"
    payload = llm.session.post.call_args.kwargs["json"]
    assert "temperature" not in payload


def test_generate_stream_includes_explicit_numeric_temperature():
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"x"}}]}',
        "data: [DONE]",
    ]
    llm.session.post = MagicMock(return_value=response)

    list(llm.generate_stream("Test", temperature=0.4))
    payload = llm.session.post.call_args.kwargs["json"]
    assert payload["temperature"] == 0.4


def test_kwargs_override_temperature_when_passed_via_kwargs():
    llm = _make_llm()
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    llm._post = MagicMock(return_value=response)

    # Kwarg-only path: must serialise the explicit value
    llm.generate("Test", temperature=0.5)
    payload = llm._post.call_args.args[1]
    assert payload["temperature"] == 0.5


def test_generate_stream_omits_unset_max_tokens() -> None:
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = ["data: [DONE]"]
    llm.session.post = MagicMock(return_value=response)

    list(llm.generate_stream("Test", max_tokens=None))

    assert "max_tokens" not in llm.session.post.call_args.kwargs["json"]
    assert "max_completion_tokens" not in llm.session.post.call_args.kwargs["json"]


def test_generate_stream_sends_only_an_explicit_output_limit() -> None:
    llm = _make_llm()
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.ok = True
    response.encoding = "utf-8"
    response.iter_lines.return_value = ["data: [DONE]"]
    llm.session.post = MagicMock(return_value=response)

    list(llm.generate_stream("Test", max_tokens=6126))

    payload = llm.session.post.call_args.kwargs["json"]
    assert payload["max_tokens"] == 6126
    assert "max_completion_tokens" not in payload


def test_count_chat_input_tokens_uses_final_template_and_no_retries() -> None:
    llm = _make_llm(enable_thinking=True)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"tokens": 42}
    llm._post = MagicMock(return_value=response)

    count = llm.count_chat_input_tokens([{"role": "user", "content": "hello"}])

    assert count == 42
    llm._post.assert_called_once_with(
        "/v1/chat/completions/input_tokens",
        {
            "model": "local-model",
            "messages": [{"role": "user", "content": "hello"}],
            "chat_template_kwargs": {"enable_thinking": True},
        },
        retries=0,
    )


def test_tokenize_returns_length_of_host_token_list() -> None:
    llm = _make_llm()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"tokens": [1, 2, 3]}
    llm._post = MagicMock(return_value=response)

    assert llm.tokenize("abc") == 3


@pytest.mark.parametrize("status", [404, 405])
def test_missing_token_count_endpoint_is_distinct(status: int) -> None:
    llm = _make_llm()
    response = MagicMock()
    response.status_code = status
    llm._post = MagicMock(return_value=response)

    with pytest.raises(LLMTokenCountUnsupportedError):
        llm.tokenize("abc")


def test_invalid_token_count_response_is_an_error() -> None:
    llm = _make_llm()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"tokens": "not-a-list"}
    llm._post = MagicMock(return_value=response)

    with pytest.raises(LLMTokenCountError):
        llm.tokenize("abc")
