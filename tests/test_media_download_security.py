"""Security tests for verified media redirect handling."""
from email.message import Message
from unittest.mock import patch
import urllib.error

import pytest

from actions.media import _download_media_bytes, _validated_source_url


class _Response:
    """Minimal context-managed urllib response."""

    def __init__(self, payload: bytes = b"image", content_type: str = "image/png"):
        self.payload = payload
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": content_type,
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class _RedirectOpener:
    """Return one redirect followed by one successful response."""

    def __init__(self, location: str):
        self.location = location
        self.calls = []

    def open(self, request, timeout: int):
        self.calls.append(request.full_url)
        if len(self.calls) == 1:
            headers = Message()
            headers["Location"] = self.location
            raise urllib.error.HTTPError(
                request.full_url, 302, "Found", headers, None
            )
        return _Response()


def test_source_url_rejects_credentials_and_nonstandard_ports() -> None:
    """Allowlisted hosts cannot be reached through credential or port tricks."""
    assert _validated_source_url("https://user@github.com/file") is None
    assert _validated_source_url("https://github.com:444/file") is None
    assert _validated_source_url("http://github.com/file") is None


def test_allowed_redirect_chain_is_revalidated() -> None:
    """Each redirect may continue only to another allowlisted HTTPS host."""
    opener = _RedirectOpener(
        "https://private-user-images.githubusercontent.com/assets/image.png"
    )
    with patch("urllib.request.build_opener", return_value=opener):
        payload, content_type = _download_media_bytes(
            "https://github.com/user-attachments/assets/image"
        )

    assert payload == b"image"
    assert content_type == "image/png"
    assert len(opener.calls) == 2


def test_redirect_to_untrusted_host_is_rejected_before_request() -> None:
    """An allowlisted source cannot bounce the publisher to an arbitrary host."""
    opener = _RedirectOpener("https://example.com/private")
    with patch("urllib.request.build_opener", return_value=opener):
        with pytest.raises(ValueError, match="redirect target is not allowed"):
            _download_media_bytes(
                "https://github.com/user-attachments/assets/image"
            )

    assert len(opener.calls) == 1
