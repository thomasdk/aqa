"""Run the isolated backend and deterministic provider used by product browser tests."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PORT = 4174
PROVIDER_PORT = 4175
PRODUCT_URL = f"http://127.0.0.1:{PRODUCT_PORT}/api/health"
PROVIDER_URL = f"http://127.0.0.1:{PROVIDER_PORT}/v1/models"
MODEL_ID = "aqa-e2e-model"
EXPLICIT_OVERRIDE_MODEL_ID = "aqa-e2e-override-model"
PROVIDER_MODE_ENV = "AQA_E2E_PROVIDER_MODE"
PROVIDER_MODE_HEADER = "X-AQA-E2E-Mode"
SUSTAINED_STREAM_SENTINEL = "AQA_E2E_SUSTAINED_STREAM"
SUSTAINED_STREAM_CHUNKS = 240
SUSTAINED_STREAM_INTERVAL_SECONDS = 0.02
_USER_DATA_ENVIRONMENT = (
    "AQA_PACKAGED_MODE",
    "AQA_USER_DATA_DIR",
    "AQA_SETTINGS_PATH",
    "AQA_CONVERSATIONS_DIR",
    "PROMPT_LIBRARY_PATH",
    "PROMPT_DEFAULTS_PATH",
    "AQA_PROMPT_DEFAULTS_DIR",
    "AQA_LOCAL_AI_DIR",
    "AQA_SYNC_PROMPTS_FROM_SOURCE",
)

provider = FastAPI(title="AQA product-test OpenAI-compatible provider")


def _provider_mode(request: Request) -> str:
    """Resolve a named loopback fault mode from the request or child process."""
    return request.headers.get(PROVIDER_MODE_HEADER) or os.environ.get(PROVIDER_MODE_ENV, "normal")


def _provider_state() -> SimpleNamespace:
    state = provider.state
    if not hasattr(state, "model_list_calls"):
        state.model_list_calls = 0
    if not hasattr(state, "delayed_started"):
        state.delayed_started = threading.Event()
    if not hasattr(state, "delayed_release"):
        state.delayed_release = threading.Event()
    return state


@provider.get("/v1/models")
def list_models(request: Request) -> JSONResponse:
    mode = _provider_mode(request)
    state = _provider_state()
    state.model_list_calls += 1
    if mode == "auth_failure":
        return JSONResponse({"error": "authentication required"}, status_code=401)
    model: dict[str, object] = {"id": MODEL_ID, "object": "model"}
    if mode == "changing_model_list" and state.model_list_calls > 1:
        model["id"] = f"{MODEL_ID}-changed"
    if mode == "tiny_context":
        model["context_length"] = 16
    return JSONResponse(
        {
            "object": "list",
            "data": [model, {"id": EXPLICIT_OVERRIDE_MODEL_ID, "object": "model"}],
        }
    )


def _stream_events(mode: str, slow: bool) -> Iterator[str]:
    yield 'data: {"choices":[{"delta":{"content":"Deterministic "}}]}\n\n'
    if mode == "fail_after_partial_output":
        # The client must see a provider-level stream error after the visible
        # delta; a clean EOF would look like an ordinary completed response.
        yield (
            'data: {"error":{"message":"deterministic provider failure '
            'after partial output","type":"server_error"}}\n\n'
        )
        return
    if mode == "delayed_writes":
        state = _provider_state()
        state.delayed_started.set()
        if not state.delayed_release.wait(timeout=10):
            raise RuntimeError("deterministic delayed-write barrier was not released")
    elif slow:
        # The product test cancels while this provider deliberately withholds
        # the terminal chunk. No model or external service is involved.
        time.sleep(1.5)
    if mode == "empty_completion":
        yield 'data: {"choices":[],"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}\n\n'
        yield "data: [DONE]\n\n"
        return
    if mode == "sustained_generation":
        for index in range(SUSTAINED_STREAM_CHUNKS):
            content = f"\n- Evidence {index + 1}: **stable** `Z{index % 10000:04d}`."
            yield f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n\n"
            time.sleep(SUSTAINED_STREAM_INTERVAL_SECONDS)
    yield 'data: {"choices":[{"delta":{"content":"analysis."}}]}\n\n'
    if mode != "missing_usage":
        usage = (
            '{"prompt_tokens":"bad","completion_tokens":null,"total_tokens":-1}'
            if mode == "malformed_usage"
            else '{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}'
        )
        yield f'data: {{"choices":[],"usage":{usage}}}\n\n'
    yield "data: [DONE]\n\n"


@provider.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    payload = await request.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    mode = _provider_mode(request)
    if SUSTAINED_STREAM_SENTINEL in serialized:
        mode = "sustained_generation"
    if mode == "fail_before_output":
        return JSONResponse(
            {
                "error": {
                    "message": "deterministic provider failure before output",
                    "type": "server_error",
                }
            },
            status_code=503,
        )
    if mode == "auth_failure":
        return JSONResponse({"error": "authentication required"}, status_code=401)
    return StreamingResponse(
        _stream_events(mode, "AQA_E2E_SLOW_STOP" in serialized),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _wait_for_health(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"test process exited before health check: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {url}")


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _product_environment(user_data_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for variable in _USER_DATA_ENVIRONMENT:
        environment.pop(variable, None)
    environment["AQA_USER_DATA_DIR"] = str(user_data_dir)
    environment["AQA_SYNC_PROMPTS_FROM_SOURCE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def run_product_server() -> int:
    if not (PROJECT_ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError(
            "frontend/dist is missing; run npm run build before product browser tests"
        )

    provider_process: subprocess.Popen[bytes] | None = None
    product_process: subprocess.Popen[bytes] | None = None
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def stop_server(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    with tempfile.TemporaryDirectory(prefix="aqa-product-e2e-") as temporary_dir:
        environment = _product_environment(Path(temporary_dir) / "User Data")
        try:
            provider_process = subprocess.Popen(
                [sys.executable, __file__, "--provider"],
                cwd=PROJECT_ROOT,
                env=environment,
            )
            _wait_for_health(PROVIDER_URL, provider_process)
            product_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "src.api_server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PRODUCT_PORT),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
            )
            _wait_for_health(PRODUCT_URL, product_process)
            while product_process.poll() is None:
                time.sleep(0.25)
            return product_process.returncode or 0
        finally:
            _terminate(product_process)
            _terminate(provider_process)
            signal.signal(signal.SIGTERM, previous_sigterm_handler)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated AQA browser-test backend or loopback provider.",
        epilog=(
            "For the EXT-14 fixture, run two provider processes on distinct loopback ports, "
            "create two credential-free hosts in the disposable GUI profile, and explicitly "
            f"select {EXPLICIT_OVERRIDE_MODEL_ID} for the unrelated Perspective."
        ),
    )
    parser.add_argument("--provider", action="store_true", help="run only the provider fixture")
    parser.add_argument(
        "--provider-port",
        type=int,
        default=PROVIDER_PORT,
        help="loopback provider port (default: %(default)s)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    if arguments.provider:
        if not 1024 <= arguments.provider_port <= 65535:
            raise SystemExit("--provider-port must be between 1024 and 65535")
        import uvicorn

        uvicorn.run(provider, host="127.0.0.1", port=arguments.provider_port, log_level="warning")
    else:
        try:
            raise SystemExit(run_product_server())
        except KeyboardInterrupt:
            raise SystemExit(0) from None
