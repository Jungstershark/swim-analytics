"""ASGI regression tests for pre-multipart upload body limits."""

import asyncio

import pytest
from fastapi import HTTPException

from app import main


class _ReceiveChunks:
    def __init__(self, chunks: list[bytes]):
        self._chunks = iter(chunks)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        try:
            body = next(self._chunks)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {
            "type": "http.request",
            "body": body,
            "more_body": True,
        }


def _scope(path: str, headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }


def _invoke_app(path: str, headers: list[tuple[bytes, bytes]], chunks: list[bytes]):
    sent: list[dict] = []
    receive = _ReceiveChunks(chunks)

    async def send(message: dict):
        sent.append(message)

    asyncio.run(main.app(_scope(path, headers), receive, send))
    return sent, receive


def _replace_upload_route_app(monkeypatch: pytest.MonkeyPatch, path: str, entered: list[str]) -> None:
    route = next(route for route in main.app.routes if getattr(route, "path", None) == path)

    async def handler(scope, receive, send):
        entered.append(path)
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    monkeypatch.setattr(route, "app", handler)


@pytest.mark.parametrize("path", ["/api/upload", "/api/upload/preview"])
def test_upload_routes_reject_oversized_content_length_before_handlers(path: str, monkeypatch: pytest.MonkeyPatch):
    entered: list[str] = []
    _replace_upload_route_app(monkeypatch, path, entered)

    sent, receive = _invoke_app(
        path,
        [
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"content-length", str(main.MAX_UPLOAD_BYTES + 1).encode()),
        ],
        [],
    )

    assert entered == []
    assert receive.calls == 0
    assert sent[0]["status"] == 413


@pytest.mark.parametrize("path", ["/api/upload", "/api/upload/preview"])
def test_upload_routes_reject_oversized_chunked_bodies_before_handlers(path: str, monkeypatch: pytest.MonkeyPatch):
    entered: list[str] = []
    _replace_upload_route_app(monkeypatch, path, entered)
    max_sized_chunk = b"x" * main.MAX_UPLOAD_BYTES

    sent, receive = _invoke_app(
        path,
        [(b"content-type", b"multipart/form-data; boundary=test")],
        [max_sized_chunk, b"x"],
    )

    assert entered == []
    assert receive.calls == 2
    assert sent[0]["status"] == 413


@pytest.mark.parametrize("path", ["/api/upload", "/api/upload/preview"])
def test_small_multipart_bodies_reach_upload_handlers(path: str, monkeypatch: pytest.MonkeyPatch):
    entered: list[str] = []

    def reject_after_handler_entry(file):
        entered.append(path)
        raise HTTPException(status_code=418, detail="upload handler reached")

    body = (
        b"--test\r\n"
        b'Content-Disposition: form-data; name="file"; filename="small.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        b"%PDF-1.4 fixture\r\n"
        b"--test--\r\n"
    )
    monkeypatch.setattr(main, "_extract_pdfs_from_upload", reject_after_handler_entry)

    sent, _receive = _invoke_app(
        path,
        [
            (b"content-type", b"multipart/form-data; boundary=test"),
            (b"content-length", str(len(body)).encode()),
        ],
        [body[:32], body[32:]],
    )

    assert entered == [path]
    assert sent[0]["status"] == 418
