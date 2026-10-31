import asyncio

import pytest
from starlette.requests import ClientDisconnect

from app.errors import ApiError
from app.main import read_json, read_upload
from app.schemas import TextRequest


class FakeRequest:
    def __init__(self, content_type, chunks, disconnect=False, content_length=None):
        self.headers = {"content-type": content_type}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self._chunks = chunks
        self._disconnect = disconnect

    async def stream(self):
        for chunk in self._chunks:
            yield chunk
        if self._disconnect:
            raise ClientDisconnect()


@pytest.mark.parametrize("reader,ctype", [
    (lambda r: read_upload(r, 10_000), "multipart/form-data; boundary=abc"),
    (lambda r: read_json(r, TextRequest, 10_000), "application/json"),
])
def test_client_disconnect_mid_body_is_a_400_not_a_500(reader, ctype):
    with pytest.raises(ApiError) as exc:
        asyncio.run(reader(FakeRequest(ctype, [b"--abc\r\n"], disconnect=True)))
    assert (exc.value.status, exc.value.code) == (400, "E_BAD_REQUEST")


def test_json_reader_enforces_the_cap_while_streaming():
    with pytest.raises(ApiError) as exc:
        asyncio.run(read_json(FakeRequest("application/json", [b"x" * 600] * 10), TextRequest, 1024))
    assert exc.value.status == 413


def test_json_reader_accepts_a_charset_parameter():
    req = FakeRequest("application/json; charset=utf-8", [b'{"text": "XIC(A)OTE(B);"}'])
    assert asyncio.run(read_json(req, TextRequest, 1024)).text == "XIC(A)OTE(B);"
