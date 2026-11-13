"""Persistent configuration and queue. Atomic writes mitigate incomplete JSON on shutdown.
All application data files (`settings.json`, `jobs.json`, `updates/`, `bin/`) are stored inside
`C:\\Users\\<User>\\youtube_desktop_downloader_data`.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .models import Job, Settings
from .version import app_data_dir, default_download_dir


def config_dir() -> Path:
    return app_data_dir()


def peek_theme_mode() -> str:
    """Fast, zero-overhead theme mode extraction from settings.json without loading Qt."""
    try:
        p = config_dir() / "settings.json"
        if p.is_file():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                mode = str(data.get("theme_mode") or "").strip().lower()
                if mode in {"system", "light", "dark"}:
                    return mode
    except Exception:
        pass
    return "system"


def _normalize_download_dir(raw_dir: str) -> str:
    """Ensure `download_dir` is valid on the current machine, migrating legacy defaults
    (`YouTube Downloads`, `dist\\Downloads`) or paths from another PC's user profile
    to `<CurrentUser>\\Downloads\\YouTube Desktop Downloader`.
    """
    fallback = str(default_download_dir())
    cleaned = (raw_dir or "").strip()
    if not cleaned:
        return fallback

    norm = cleaned.replace("/", "\\").rstrip("\\").lower()
    if (
        norm.endswith("\\downloads\\youtube downloads")
        or norm.endswith("\\dist\\downloads")
        or norm.endswith("\\youtubedesktopdownloader\\downloads")
    ):
        return fallback

    # If the path references C:\Users\<SomeOtherUser>\... that doesn't exist on this PC, reset to fallback
    m = re.match(r"^([a-zA-Z]:\\users\\[^\\]+)(?:\\|$)", cleaned, re.IGNORECASE)
    if m:
        user_profile_dir = Path(m.group(1))
        if not user_profile_dir.exists():
            return fallback

    try:
        candidate = Path(cleaned).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        return str(candidate)
    except OSError:
        try:
            default_download_dir().mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback


class Storage:
    def __init__(self, base: Path | None = None):
        self.base = base or config_dir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.config_path = self.base / "settings.json"
        self.jobs_path = self.base / "jobs.json"

    @staticmethod
    def _read(path: Path, default):
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    @staticmethod
    def _write(path: Path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                return
            except OSError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def load_settings(self) -> Settings:
        raw = self._read(self.config_path, {})
        try:
            settings = Settings.from_dict(raw if isinstance(raw, dict) else {})
            settings.max_concurrent = max(1, min(5, int(settings.max_concurrent)))
            settings.fragment_connections = max(1, min(8, int(settings.fragment_connections)))
            if settings.fragment_connections <= 1:
                settings.fragment_connections = 4
            settings.download_dir = _normalize_download_dir(settings.download_dir)
            settings.portable_mode = True
            settings.update_manifest_url = ""
            if settings.cookie_file and not Path(settings.cookie_file).expanduser().is_file():
                # Clear invalid cookie file path if copied from another machine
                settings.cookie_file = ""
            # Ensure auto_check_updates defaults to True for v2.7+ if not explicitly customized
            if "auto_check_updates" not in (raw if isinstance(raw, dict) else {}):
                settings.auto_check_updates = True
            return settings
        except (TypeError, ValueError):
            return Settings()

    def save_settings(self, settings: Settings):
        from dataclasses import asdict
        self._write(self.config_path, asdict(settings))

    def load_jobs(self) -> list[Job]:
        raw = self._read(self.jobs_path, [])
        if not isinstance(raw, list):
            return []
        jobs = []
        for data in raw[:3000]:
            if not isinstance(data, dict):
                continue
            try:
                job = Job.from_dict(data)
                # Recover zombie jobs from sudden shutdowns/crashes
                if job.status in {"downloading", "processing", "converting"}:
                    job.status = "paused"
                    job.speed = ""
                    job.eta = ""
                if job.status == "queued":
                    job.directory = _normalize_download_dir(job.directory)
                jobs.append(job)
            except (TypeError, ValueError, KeyError):
                continue
        return jobs

    def save_jobs(self, jobs: list[Job]):
        self._write(self.jobs_path, [item.to_dict() for item in jobs[-3000:]])
