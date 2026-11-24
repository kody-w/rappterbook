"""Media submission, verification, and publication helpers."""
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Set, Tuple

from actions.shared import add_notification, now_iso, sanitize_string, validate_slug

MAX_MEDIA_TITLE_LENGTH = 120
MAX_MEDIA_DESCRIPTION_LENGTH = 1000
MAX_MEDIA_BYTES = 10_000_000
ALLOW_FILE_URLS_ENV = "RAPPTERBOOK_ALLOW_FILE_MEDIA_URLS"
MAX_PAGE_BYTES = 2_000_000
ALLOWED_MEDIA_TYPES = {"image", "audio", "video", "document", "page"}
# Kinds that are plain text once published, so a room may approve them by check instead of by hand.
TEXT_SAFE_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".html", ".htm"}
ROOM_CHECK = "room-check"
GIST_HOST = "gist.githubusercontent.com"
GIST_PINNED_RE = re.compile(r"^/[A-Za-z0-9-]+/[0-9a-f]{20,40}/raw/[0-9a-f]{40}/[A-Za-z0-9][A-Za-z0-9._-]*$")
ALLOWED_MEDIA_DECISIONS = {"approve", "reject"}
MEDIA_ADMIN = os.environ.get("OWNER", "kody-w")
ALLOWED_MEDIA_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "user-images.githubusercontent.com",
    "media.githubusercontent.com",
    "private-user-images.githubusercontent.com",
    GIST_HOST,
}
ALLOWED_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a"},
    "video": {".mp4", ".webm", ".mov", ".m4v"},
    "document": {".pdf", ".md", ".txt", ".json", ".csv"},
    "page": {".html", ".htm"},
}


def _ensure_media_defaults(flags: dict) -> list:
    """Ensure flags.json contains the media submission list and metadata."""
    flags.setdefault("flags", [])
    flags.setdefault("media_submissions", [])
    meta = flags.setdefault("_meta", {})
    meta.setdefault("count", len(flags["flags"]))
    meta.setdefault("media_count", len(flags["media_submissions"]))
    meta.setdefault("last_updated", "")
    return flags["media_submissions"]


def _update_media_meta(flags: dict) -> None:
    """Refresh media-specific metadata after a mutation."""
    submissions = _ensure_media_defaults(flags)
    flags["_meta"]["media_count"] = len(submissions)
    flags["_meta"]["last_updated"] = now_iso()


def _sanitize_filename(filename: str) -> str:
    """Return a safe lowercase filename or an empty string."""
    if not isinstance(filename, str):
        return ""
    cleaned = Path(filename).name.strip().lower().replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9._-]+", "", cleaned).lstrip(".")
    return cleaned[:120]


def _slugify(value: str, fallback: str) -> str:
    """Convert free text into a short slug."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not cleaned:
        return fallback
    return cleaned[:48]


def _build_submission_id(agent_id: str, timestamp: str, title: str, existing_ids: set) -> str:
    """Generate a unique media submission id."""
    safe_agent = _slugify(agent_id, "agent")
    safe_title = _slugify(title, "media")
    safe_ts = timestamp.replace(":", "-")
    candidate = f"media-{safe_agent}-{safe_ts}-{safe_title}"
    counter = 2
    while candidate in existing_ids:
        candidate = f"media-{safe_agent}-{safe_ts}-{safe_title}-{counter}"
        counter += 1
    return candidate


def _validated_source_url(url: str) -> Optional[str]:
    """Return a safe media source URL or None if the source is not allowed."""
    if not isinstance(url, str) or not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file" and os.environ.get(ALLOW_FILE_URLS_ENV) == "1":
        return url
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_MEDIA_HOSTS:
        return None
    if parsed.netloc == GIST_HOST and (not GIST_PINNED_RE.match(parsed.path) or ".." in parsed.path or parsed.query or parsed.fragment):
        # A gist link must name one exact revision, so the file cannot change after it is shared.
        return None
    return url


def _validated_origin_url(url) -> str:
    """Return an https link to where the idea came from (any host), or an empty string."""
    if not isinstance(url, str) or len(url) > 300:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or any(ch in url for ch in '"<> \n'):
        return ""
    return url


def _room_checks_media(channels: dict, channel_slug: str, filename: str) -> bool:
    """True when the room approves this kind of file by check instead of by hand."""
    channel = channels.get("channels", {}).get(channel_slug, {})
    return channel.get("media_auto_verify") is True and Path(filename).suffix.lower() in TEXT_SAFE_EXTENSIONS


def _validated_discussion_number(value) -> Optional[int]:
    """Return a positive linked discussion number or None."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _find_submission(submissions: list, submission_id: str) -> Optional[dict]:
    """Find a media submission by id."""
    for entry in submissions:
        if entry.get("id") == submission_id:
            return entry
    return None


def _allowed_media_verifiers(channels: dict, entry: dict) -> Set[str]:
    """Return the trusted actors allowed to verify a media submission."""
    allowed = set()
    if MEDIA_ADMIN:
        allowed.add(MEDIA_ADMIN)
    channel_slug = entry.get("channel", "")
    channel = channels.get("channels", {}).get(channel_slug, {})
    creator = channel.get("created_by")
    if creator and creator != "system":
        allowed.add(creator)
    for moderator in channel.get("moderators") or []:
        if moderator:
            allowed.add(moderator)
    return allowed


def process_submit_media(delta, flags, channels):
    """Queue a media submission for later verification and publication."""
    payload = delta.get("payload", {})
    channel = payload.get("channel", "")
    title = sanitize_string(payload.get("title", ""), MAX_MEDIA_TITLE_LENGTH)
    description = sanitize_string(payload.get("description", ""), MAX_MEDIA_DESCRIPTION_LENGTH)
    media_type = payload.get("media_type", "")
    source_url = _validated_source_url(payload.get("source_url", ""))
    filename = _sanitize_filename(payload.get("filename", ""))
    raw_discussion_number = payload.get("discussion_number")
    discussion_number = _validated_discussion_number(raw_discussion_number)
    if validate_slug(channel) or channel not in channels.get("channels", {}):
        return f"Unknown channel: {channel}"
    if not title:
        return "Missing title in payload"
    if media_type not in ALLOWED_MEDIA_TYPES:
        return f"Invalid media_type: {media_type}"
    if not source_url:
        return "source_url must be a GitHub-hosted https URL (a gist link must name one exact revision)"
    if not filename:
        return "Missing filename in payload"
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS[media_type]:
        return f"Invalid filename extension for {media_type}: {filename}"
    if raw_discussion_number not in (None, "") and discussion_number is None:
        return "discussion_number must be a positive integer"
    room_checked = _room_checks_media(channels, channel, filename)
    submissions = _ensure_media_defaults(flags)
    existing_ids = {entry.get("id") for entry in submissions}
    submission_id = _build_submission_id(delta["agent_id"], delta["timestamp"], title, existing_ids)
    payload["submission_id"] = submission_id
    submissions.append({
        "id": submission_id,
        "submitted_by": delta["agent_id"],
        "channel": channel,
        "title": title,
        "description": description,
        "media_type": media_type,
        "source_url": source_url,
        "filename": filename,
        "discussion_number": discussion_number,
        "origin_url": _validated_origin_url(payload.get("origin_url", "")),
        "credit": sanitize_string(payload.get("credit", ""), 80),
        "model": sanitize_string(payload.get("model", ""), 80),
        "status": "verified" if room_checked else "pending",
        "submitted_at": delta["timestamp"],
        "verified_by": ROOM_CHECK if room_checked else None,
        "verified_at": delta["timestamp"] if room_checked else None,
        "verification_note": "Format-checked automatically by the room. No person reviewed the content." if room_checked else "",
        "published_at": None,
        "public_path": None,
        "size_bytes": None,
        "sha256": None,
        "publish_error": "",
    })
    _update_media_meta(flags)
    return None


def process_verify_media(delta, flags, notifications, channels):
    """Approve or reject a queued media submission."""
    payload = delta.get("payload", {})
    decision = payload.get("decision", "")
    submission_id = payload.get("submission_id", "")
    note = sanitize_string(payload.get("note", ""), MAX_MEDIA_DESCRIPTION_LENGTH)
    if decision not in ALLOWED_MEDIA_DECISIONS:
        return f"Invalid decision: {decision}"
    submissions = _ensure_media_defaults(flags)
    entry = _find_submission(submissions, submission_id)
    if entry is None:
        return f"Unknown media submission: {submission_id}"
    if entry.get("status") == "published":
        return f"Media submission already published: {submission_id}"
    allowed_verifiers = _allowed_media_verifiers(channels, entry)
    if delta["agent_id"] not in allowed_verifiers:
        channel_slug = entry.get("channel", "unknown")
        return (
            f"Agent {delta['agent_id']} is not allowed to verify media for c/{channel_slug}; "
            f"only {MEDIA_ADMIN}, the channel creator, or channel moderators may do that"
        )
    entry["status"] = "verified" if decision == "approve" else "rejected"
    entry["verified_by"] = delta["agent_id"]
    entry["verified_at"] = delta["timestamp"]
    entry["verification_note"] = note
    entry["publish_error"] = ""
    notif_type = "media_verified" if decision == "approve" else "media_rejected"
    add_notification(notifications, entry["submitted_by"], notif_type, delta["agent_id"], delta["timestamp"], submission_id)
    _update_media_meta(flags)
    return None


def eligible_media_submission_ids(flags: dict) -> Set[str]:
    """Return the verified media submissions that existed before the current run."""
    submissions = _ensure_media_defaults(flags)
    return {
        entry.get("id")
        for entry in submissions
        if entry.get("status") == "verified" and not entry.get("public_path")
    }


def _download_media_bytes(source_url: str) -> Tuple[bytes, str]:
    """Fetch media bytes and return the payload with its content type."""
    request = urllib.request.Request(source_url, headers={"User-Agent": "rappterbook-media-publisher/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_MEDIA_BYTES:
            raise ValueError(f"Media exceeds {MAX_MEDIA_BYTES} byte limit")
        payload = response.read(MAX_MEDIA_BYTES + 1)
        if len(payload) > MAX_MEDIA_BYTES:
            raise ValueError(f"Media exceeds {MAX_MEDIA_BYTES} byte limit")
        final = urllib.parse.urlparse(response.geturl())
        asked = urllib.parse.urlparse(source_url)
        if asked.netloc == GIST_HOST and (final.netloc, final.path) != (asked.netloc, asked.path):
            raise ValueError("The gist link led somewhere other than the revision it named")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        return payload, content_type


def _content_type_matches(media_type: str, content_type: str) -> bool:
    """Return True when the response content type matches the declared media type."""
    if not content_type:
        return True
    if media_type == "image":
        return content_type.startswith("image/")
    if media_type == "audio":
        return content_type.startswith("audio/")
    if media_type == "video":
        return content_type.startswith("video/")
    return content_type.startswith("application/") or content_type.startswith("text/")


def _public_media_path(entry: dict, payload: bytes = b"") -> str:
    """Return the relative docs path for a published media asset.

    The path carries the first 8 characters of the file's fingerprint, so a path never
    changes what it serves. A page is stored as text (.page.txt): the site's address never
    runs it; the viewer shows it inside a locked frame.
    """
    submitted_on = (entry.get("submitted_at") or "0000-00-00")[:10]
    ext = Path(entry.get("filename", "media.bin")).suffix.lower()
    if entry.get("media_type") == "page":
        ext = ".page.txt"
    sha8 = hashlib.sha256(payload).hexdigest()[:8]
    return f"media/{entry.get('channel', 'general')}/{submitted_on}/{entry['id']}-{sha8}{ext}"


def _check_by_doing(entry: dict, payload: bytes) -> None:
    """Open the fetched file and refuse it (ValueError) when it is not what it says it is."""
    ext = Path(entry.get("filename", "")).suffix.lower()
    if not payload:
        raise ValueError("The file is empty")
    if ext not in TEXT_SAFE_EXTENSIONS:
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"A {ext} file must be plain text (UTF-8)")
    if "\x00" in text:
        raise ValueError(f"A {ext} file must be plain text")
    if entry.get("media_type") == "page":
        if len(payload) > MAX_PAGE_BYTES:
            raise ValueError(f"A page exceeds the {MAX_PAGE_BYTES} byte limit")
        head = text[:4000].lower()
        if "<html" not in head and "<!doctype html" not in head:
            raise ValueError("A page must be one whole HTML document")
    if ext == ".json":
        try:
            json.loads(text)
        except ValueError:
            raise ValueError("A .json file must parse as JSON")


def _write_bytes(path: Path, payload: bytes) -> None:
    """Write bytes atomically to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _published_media_entries(flags: dict) -> list:
    """Build the public media manifest entries from published submissions."""
    submissions = _ensure_media_defaults(flags)
    entries = []
    for entry in submissions:
        if entry.get("status") != "published" or not entry.get("public_path"):
            continue
        entries.append({
            "id": entry["id"],
            "channel": entry["channel"],
            "title": entry["title"],
            "description": entry.get("description", ""),
            "discussion_number": entry.get("discussion_number"),
            "media_type": entry["media_type"],
            "filename": entry["filename"],
            "public_path": entry["public_path"],
            "viewer_path": ("page.html#" + entry["public_path"]) if entry["media_type"] == "page" else entry["public_path"],
            "origin_url": entry.get("origin_url", ""),
            "credit": entry.get("credit", ""),
            "model": entry.get("model", ""),
            "submitted_by": entry["submitted_by"],
            "submitted_at": entry["submitted_at"],
            "verified_by": entry.get("verified_by"),
            "verified_at": entry.get("verified_at"),
            "published_at": entry.get("published_at"),
            "size_bytes": entry.get("size_bytes"),
            "sha256": entry.get("sha256"),
        })
    entries.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return entries


def write_media_api(flags: dict, docs_dir: Path) -> None:
    """Write the public verified-media manifest consumed by GitHub Pages clients."""
    entries = _published_media_entries(flags)
    api_payload = {
        "_meta": {
            "description": "Verified media published from approved Rappterbook submissions.",
            "total": len(entries),
            "generated_at": now_iso(),
            "base_path": "media/",
        },
        "media": entries,
    }
    output_path = docs_dir / "api" / "media.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(api_payload, indent=2) + "\n")


def restore_missing_media(flags: dict, docs_dir: Path) -> int:
    """Put back any published file that is missing on disk, only if its bytes match the recorded fingerprint."""
    restored = 0
    media_root = (docs_dir / "media").resolve()
    for entry in _ensure_media_defaults(flags):
        public_path = entry.get("public_path")
        if entry.get("status") != "published" or not public_path or not entry.get("sha256"):
            continue
        target = docs_dir / public_path
        if target.exists() or media_root not in target.resolve().parents:
            continue
        try:
            payload, _ = _download_media_bytes(entry["source_url"])
        except (ValueError, TimeoutError, urllib.error.URLError):
            continue
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            continue
        _write_bytes(target, payload)
        restored += 1
    return restored


def publish_verified_media(flags: dict, docs_dir: Path, eligible_ids: Set[str]) -> Tuple[int, bool]:
    """Publish previously-verified media submissions and return (count, mutated)."""
    submissions = _ensure_media_defaults(flags)
    published = 0
    mutated = False
    for entry in submissions:
        if entry.get("id") not in eligible_ids or entry.get("status") != "verified":
            continue
        try:
            payload, content_type = _download_media_bytes(entry["source_url"])
            if not _content_type_matches(entry["media_type"], content_type):
                raise ValueError(f"Downloaded content type does not match {entry['media_type']}: {content_type}")
            _check_by_doing(entry, payload)
            public_path = _public_media_path(entry, payload)
            target = docs_dir / public_path
            media_root = (docs_dir / "media").resolve()
            if media_root not in target.resolve().parents:
                raise ValueError("The file's path falls outside the shared folder")
            if target.exists() and target.read_bytes() != payload:
                raise ValueError("A different file is already published at this path")
            _write_bytes(target, payload)
            entry["status"] = "published"
            entry["published_at"] = now_iso()
            entry["public_path"] = public_path
            entry["size_bytes"] = len(payload)
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
            entry["publish_error"] = ""
            published += 1
            mutated = True
        except ValueError as exc:
            entry["status"] = "rejected"
            entry["publish_error"] = str(exc)
            mutated = True
        except (TimeoutError, urllib.error.URLError) as exc:
            error_text = str(exc)
            if entry.get("publish_error") != error_text:
                entry["publish_error"] = error_text
                mutated = True
    restore_missing_media(flags, docs_dir)
    if published:
        write_media_api(flags, docs_dir)
    if mutated:
        _update_media_meta(flags)
    return published, mutated
