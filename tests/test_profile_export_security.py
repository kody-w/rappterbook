"""Static guards for browser credential and profile-export boundaries."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_auth_tokens_are_not_persisted_in_local_storage() -> None:
    """Auth may migrate legacy keys but never writes new persistent tokens."""
    source = (ROOT / "src" / "js" / "auth.js").read_text()

    for key in ("rb_jwt", "rb_access_token", "rb_github_token"):
        assert f"localStorage.setItem('{key}'" not in source
        assert f"sessionStorage.setItem('{key}'" in source


def test_profile_export_and_import_use_preference_allowlist() -> None:
    """Profile files cannot contain or restore credentials and arbitrary keys."""
    source = (ROOT / "src" / "js" / "router.js").read_text()
    export_block = source.split("// Export profile", 1)[1].split("// Import profile", 1)[0]
    import_block = source.split("// Import profile", 1)[1].split("// Danger zone", 1)[0]

    for secret_key in (
        "rb_jwt",
        "rb_github_token",
        "rb_access_token",
        "rb_integrations_telegram",
    ):
        assert secret_key not in export_block
        assert secret_key not in import_block
    assert "const keys = ['rb-theme', 'rb_notifications_read_at']" in export_block
    assert "const allowedKeys = ['rb-theme', 'rb_notifications_read_at']" in import_block


def test_telegram_secret_is_session_scoped() -> None:
    """The optional Telegram bot token does not survive the browser session."""
    router = (ROOT / "src" / "js" / "router.js").read_text()
    render = (ROOT / "src" / "js" / "render.js").read_text()

    assert "sessionStorage.setItem('rb_integrations_telegram'" in router
    assert "sessionStorage.getItem('rb_integrations_telegram'" in render
    assert "localStorage.setItem('rb_integrations_telegram'" not in router


def test_leaflet_has_subresource_integrity() -> None:
    """Token-bearing pages pin third-party executable assets."""
    html = (ROOT / "src" / "html" / "index.html").read_text()

    leaflet_lines = [line for line in html.splitlines() if "leaflet@1.9.4" in line]
    assert len(leaflet_lines) == 2
    assert all("integrity=\"sha256-" in line for line in leaflet_lines)
    assert all('crossorigin="anonymous"' in line for line in leaflet_lines)
