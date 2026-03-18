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
ALLOWED_MEDIA_TYPES = {"image", "audio", "video", "document"}
ALLOWED_MEDIA_DECISIONS = {"approve", "reject"}
MEDIA_ADMIN = os.environ.get("OWNER", "kody-w")
ALLOWED_MEDIA_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "user-images.githubusercontent.com",
    "media.githubusercontent.com",
    "private-user-images.githubusercontent.com",
}
ALLOWED_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a"},
    "video": {".mp4", ".webm", ".mov", ".m4v"},
    "document": {".pdf", ".md", ".txt", ".json", ".csv"},
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
    return url


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
        return "source_url must be a GitHub-hosted https URL"
    if not filename:
        return "Missing filename in payload"
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS[media_type]:
        return f"Invalid filename extension for {media_type}: {filename}"
    if raw_discussion_number not in (None, "") and discussion_number is None:
        return "discussion_number must be a positive integer"
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
        "status": "pending",
        "submitted_at": delta["timestamp"],
        "verified_by": None,
        "verified_at": None,
        "verification_note": "",
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


def _public_media_path(entry: dict) -> str:
    """Return the relative docs path for a published media asset."""
    submitted_on = (entry.get("submitted_at") or "0000-00-00")[:10]
    ext = Path(entry.get("filename", "media.bin")).suffix.lower()
    return f"media/{entry.get('channel', 'general')}/{submitted_on}/{entry['id']}{ext}"


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
            public_path = _public_media_path(entry)
            _write_bytes(docs_dir / public_path, payload)
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
    if published:
        write_media_api(flags, docs_dir)
    if mutated:
        _update_media_meta(flags)
    return published, mutated
