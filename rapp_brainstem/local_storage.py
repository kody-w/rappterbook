"""
LocalStorageManager — drop-in replacement for AzureFileStorageManager.
Mirrors the CommunityRAPP storage layout:
  shared_memories/memory.json   — shared memories
  memory/{guid}/user_memory.json — per-user memories
Data lives in .brainstem_data/ next to this file.
"""

import os
import json
import logging

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".brainstem_data")


class AzureFileStorageManager:
    """
    Local-first shim that mirrors the AzureFileStorageManager API from
    CommunityRAPP.  Agents import this transparently via the shim in brainstem.py.
    """

    DEFAULT_MARKER_GUID = "c0p110t0-aaaa-bbbb-cccc-123456789abc"

    def __init__(self, share_name=None, **kwargs):
        self.current_guid = None
        # Matches CommunityRAPP paths
        self.shared_memory_path = "shared_memories"
        self.default_file_name = "memory.json"
        self.current_memory_path = self.shared_memory_path
        os.makedirs(_DATA_DIR, exist_ok=True)

    # ── Context ───────────────────────────────────────────────────────────

    def set_memory_context(self, user_guid=None):
        """Set the memory context — matches CommunityRAPP's set_memory_context."""
        if not user_guid or user_guid == self.DEFAULT_MARKER_GUID:
            self.current_guid = None
            self.current_memory_path = self.shared_memory_path
            return True

        # Valid GUID — set up user-specific path (memory/{guid})
        self.current_guid = user_guid
        self.current_memory_path = f"memory/{user_guid}"
        return True

    # ── Core I/O ──────────────────────────────────────────────────────────

    def _file_path(self):
        """Return the absolute path for the current memory file.
        Shared:  .brainstem_data/shared_memories/memory.json
        User:    .brainstem_data/memory/{guid}/user_memory.json
        """
        if self.current_guid:
            folder = os.path.join(_DATA_DIR, self.current_memory_path)
            fname = "user_memory.json"
        else:
            folder = os.path.join(_DATA_DIR, self.shared_memory_path)
            fname = self.default_file_name
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, fname)

    def read_json(self, file_path=None):
        """Read JSON data from local storage."""
        path = file_path or self._file_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def write_json(self, data, file_path=None):
        """Write JSON data to local storage."""
        path = file_path or self._file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return True

    # ── Convenience methods used by some agents ───────────────────────────

    def read_file(self, file_path):
        full = os.path.join(_DATA_DIR, file_path)
        if not os.path.exists(full):
            return None
        with open(full, "r") as f:
            return f.read()

    def write_file(self, file_path, content):
        full = os.path.join(_DATA_DIR, file_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        return True

    def list_files(self, directory=""):
        full = os.path.join(_DATA_DIR, directory)
        if not os.path.exists(full):
            return []
        return os.listdir(full)

    def delete_file(self, file_path):
        full = os.path.join(_DATA_DIR, file_path)
        if os.path.exists(full):
            os.remove(full)
            return True
        return False

    def file_exists(self, file_path):
        return os.path.exists(os.path.join(_DATA_DIR, file_path))
