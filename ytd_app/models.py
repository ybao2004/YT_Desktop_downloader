"""Data models; no Qt dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Job:
    url: str
    title: str = "Đang chờ phân tích"
    mode: str = "video"               # video | audio
    container: str = "mp4"             # video: mp4, mkv, webm / audio: mp3,m4a,flac,original
    quality: str = "best"              # video: best/2160/1440/1080/...  / audio: best
    video_codec: str = "h264"          # h264 (default) | h265 | av1 | vp9 | auto
    audio_bitrate: str = "192"         # 320 | 192 | 128
    directory: str = ""
    format_id: str = ""                # optional exact source format
    format_ext: str = ""               # for merge compatibility
    format_has_audio: bool = False
    clip_start: str = ""               # optional HH:MM:SS or MM:SS
    clip_end: str = ""                 # optional HH:MM:SS or MM:SS
    subtitles: bool = False
    sub_langs: str = "vi,en"
    embed_metadata: bool = True
    thumbnail_url: str = ""
    detected_codec: str = ""           # actual output codec (e.g. H.264, H.265, VP9, AV1)
    status: str = "queued"             # queued/downloading/paused/processing/converting/done/error/cancelled
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    filepath: str = ""
    error: str = ""
    job_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=timestamp)
    updated_at: str = field(default_factory=timestamp)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        available = {f.name for f in fields(cls)}
        selected = {k: v for k, v in data.items() if k in available}
        item = cls(**selected)
        if item.status in {"downloading", "paused", "processing", "converting"}:
            item.status = "queued"  # previous process is no longer running
            item.speed = ""
            item.eta = ""
        return item


from .version import default_download_dir


@dataclass
class Settings:
    download_dir: str = field(default_factory=lambda: str(default_download_dir()))
    max_concurrent: int = 2
    fragment_connections: int = 1
    default_mode: str = "video"
    default_video_ext: str = "mp4"
    default_audio_ext: str = "mp3"
    default_video_codec: str = "h264"  # h264 | h265 | av1 | vp9 | auto
    default_audio_bitrate: str = "192"
    hw_accel: str = "auto"             # auto | nvenc | qsv | amf | cpu
    last_quality: str = "best"
    last_geometry: str = ""
    last_playlist: bool = False
    keep_history: bool = True
    cookie_file: str = ""
    quick_download: bool = True
    notify_on_complete: bool = True
    embed_metadata: bool = True
    download_subtitles: bool = False
    subtitle_langs: str = "vi,en"
    portable_mode: bool = True
    update_manifest_url: str = ""
    auto_check_updates: bool = False
    theme_mode: str = "system"         # system | light | dark
    append_id_suffix: bool = False     # False: original title (default), True: [id] suffix

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        allowed = {f.name for f in fields(cls)}
        return cls(**{key: val for key, val in data.items() if key in allowed})

