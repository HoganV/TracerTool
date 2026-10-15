"""Independent, atomic session recovery; never writes the user's saved project."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import threading
from uuid import UUID

from .project import _atomic_json, _path, _project_document, load_project


_SUFFIX = ".recovery.json"


class RecoveryStore:
    """One validated snapshot per UUID session in an application-owned directory.

    Calls on the same instance are serialized. Missing source rasters are kept
    in recovery records, so a UI can offer relinking before installing a project.
    A snapshot is an ordinary v1 project with an additional ``recovery`` object.
    """

    def __init__(self, directory):
        self.directory = _path(directory, "recovery directory")
        self._lock = threading.RLock()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # mkdir(exist_ok=True) also succeeds for an existing read-only
            # folder. Exercise the write/flush/delete operations needed by
            # atomic snapshots before the UI decides recovery is available.
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".tracertool-write-", suffix=".tmp",
                                             dir=self.directory) as probe:
                probe.write(b"TracerTool recovery write check\n")
                probe.flush()
                os.fsync(probe.fileno())
        except OSError as exc:
            raise ValueError(f"Cannot write recovery folder {self.directory}: {exc}") from exc

    @staticmethod
    def _session_id(value) -> str:
        if not isinstance(value, str):
            raise ValueError("Recovery session_id must be a standard UUID string.")
        try:
            normalized = str(UUID(value))
        except (ValueError, AttributeError) as exc:
            raise ValueError("Recovery session_id must be a standard UUID string.") from exc
        if normalized != value.lower():
            raise ValueError("Recovery session_id must use the standard hyphenated UUID form.")
        return normalized

    def _session_path(self, session_id) -> Path:
        return self.directory / (self._session_id(session_id) + _SUFFIX)

    def _checked_path(self, value) -> tuple[Path, str]:
        try:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = self.directory / path
            if path.is_symlink():
                raise ValueError("Recovery files cannot be symbolic links.")
            path = path.resolve()
            if path.parent != self.directory or not path.name.endswith(_SUFFIX):
                raise ValueError("Choose a recovery record inside this recovery folder.")
            session_id = self._session_id(path.name[:-len(_SUFFIX)])
            if path.name != session_id + _SUFFIX:
                raise ValueError("The recovery filename does not match its canonical session UUID.")
            return path, session_id
        except (TypeError, OSError, RuntimeError) as exc:
            raise ValueError(f"Invalid recovery path: {exc}") from exc

    def save(self, session_id, terrain_path, features, settings, project_path=None) -> Path:
        """Replace only this session's snapshot after complete state validation."""
        target = self._session_path(session_id)
        terrain = _path(terrain_path, "terrain")
        saved_project = _path(project_path, "saved project") if project_path is not None else None
        if target == terrain or target == saved_project:
            raise ValueError("Recovery must use a separate path from the terrain and saved project.")
        document = _project_document(target, terrain, features, settings)
        document["recovery"] = {
            "version": 1,
            "session_id": self._session_id(session_id),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "project_path": str(saved_project) if saved_project is not None else None,
        }
        with self._lock:
            if target.is_symlink():
                raise ValueError("Recovery cannot overwrite a symbolic link.")
            if target.exists():
                try:
                    existing = load_project(target, allow_missing_terrain=True)
                except ValueError:
                    existing = None  # A damaged prior snapshot can be replaced.
                owner = existing.get("recovery") if existing is not None else None
                if existing is not None and (not isinstance(owner, dict) or owner.get("session_id") != document["recovery"]["session_id"]):
                    raise ValueError("This recovery filename contains another project. Choose a new session UUID.")
            _atomic_json(target, document)
        return target

    def load(self, path) -> dict:
        """Return validated state, original project location, and missing-DEM flag."""
        source, session_id = self._checked_path(path)
        with self._lock:
            document = load_project(source, allow_missing_terrain=True)
        recovery = document.get("recovery")
        if not isinstance(recovery, dict) or type(recovery.get("version")) is not int or recovery["version"] != 1:
            raise ValueError("This is not a supported TracerTool recovery record.")
        if recovery.get("session_id") != session_id:
            raise ValueError("The recovery session UUID does not match its filename.")
        try:
            timestamp = datetime.fromisoformat(recovery["updated_at"])
            if timestamp.tzinfo is None:
                raise ValueError("timestamp has no timezone")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("The recovery record has an invalid update time.") from exc
        project_path = recovery.get("project_path")
        if project_path is not None:
            if not isinstance(project_path, str) or not Path(project_path).is_absolute():
                raise ValueError("The recovery record has an invalid saved-project path.")
            project_path = str(_path(project_path, "saved project"))
        document["project_path"] = project_path
        document["missing_terrain"] = not Path(document["terrain_path"]).is_file()
        document["recovery_path"] = str(source)
        return document

    def list_entries(self) -> list[dict]:
        """List valid records newest first; damaged/incomplete files are ignored."""
        entries = []
        try:
            paths = list(self.directory.glob("*" + _SUFFIX))
        except OSError:
            return entries
        for path in paths:
            try:
                document = self.load(path)
                metadata = document["recovery"]
                draft = document["settings"].get("draft") or {}
                entries.append({
                    "path": str(path),
                    "session_id": metadata["session_id"],
                    "updated_at": metadata["updated_at"],
                    "project_path": document["project_path"],
                    "terrain_path": document["terrain_path"],
                    "feature_count": len(document["features"]),
                    "draft_anchor_count": len(draft.get("anchors", [])),
                    "missing_terrain": document["missing_terrain"],
                })
            except (ValueError, OSError, RecursionError, OverflowError):
                continue
        entries.sort(key=lambda item: datetime.fromisoformat(item["updated_at"]), reverse=True)
        return entries

    def discard(self, session_id) -> None:
        """Remove only this session's owned record; unrelated files are untouched."""
        target = self._session_path(session_id)
        with self._lock:
            if target.is_symlink():
                raise ValueError("Recovery cannot discard a symbolic link.")
            if target.is_file():
                try:
                    existing = load_project(target, allow_missing_terrain=True)
                except ValueError:
                    existing = None
                owner = existing.get("recovery") if existing is not None else None
                if existing is not None and (not isinstance(owner, dict) or owner.get("session_id") != self._session_id(session_id)):
                    raise ValueError("This filename contains a saved project, not this session's recovery record.")
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                raise ValueError(f"Could not discard recovery record {target.name}: {exc}") from exc
