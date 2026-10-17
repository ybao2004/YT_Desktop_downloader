"""Hardware and system telemetry (CPU, GPU, RAM, Storage, Network) and fast, non-blocking GPU encoder probing."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .version import app_data_dir

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_ENCODER_CACHE_LOCK = threading.Lock()
_ENCODER_CACHE: dict[str, list[str]] | None = None
_GPU_NAMES_CACHE: list[str] | None = None


@dataclass
class HardwareProfile:
    cpu_name: str = ""
    cpu_cores: int = 1
    cpu_threads: int = 1
    gpu_names: list[str] = field(default_factory=list)
    ram_total_gb: float = 0.0
    os_name: str = ""
    working_encoders: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class LiveMetrics:
    cpu_percent: float = 0.0
    gpu_percent: float | None = None
    gpu_mem_percent: float | None = None
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    net_down_bps: float = 0.0
    net_up_bps: float = 0.0


def format_rate(bps: float) -> str:
    if bps <= 0:
        return "0 KB/s"
    kb = bps / 1024.0
    if kb < 1024.0:
        return f"{kb:.0f} KB/s"
    return f"{kb / 1024.0:.1f} MB/s"


def _detect_cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            if name and str(name).strip():
                return str(name).strip()
        except Exception:
            pass
    return platform.processor() or platform.machine() or "CPU"


def _detect_gpu_names() -> list[str]:
    global _GPU_NAMES_CACHE
    if _GPU_NAMES_CACHE is not None:
        return list(_GPU_NAMES_CACHE)

    gpus: list[str] = []
    # 1. Fast Windows Registry adapter scan (0ms, no subprocess required!)
    if os.name == "nt":
        try:
            import winreg
            base_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}",
            )
            idx = 0
            while idx < 16:
                try:
                    sub_name = winreg.EnumKey(base_key, idx)
                    idx += 1
                    if not sub_name.startswith("0"):
                        continue
                    sub_key = winreg.OpenKey(base_key, sub_name)
                    desc, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
                    winreg.CloseKey(sub_key)
                    val = str(desc or "").strip()
                    if val and "basic display" not in val.lower() and val not in gpus:
                        gpus.append(val)
                except OSError:
                    break
            winreg.CloseKey(base_key)
        except Exception:
            pass

    # 2. Enrich with nvidia-smi if available
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi and not any("nvidia" in g.lower() for g in gpus):
        try:
            res = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        gpus.append(f"{parts[0]} ({parts[1]})")
                    elif parts and parts[0]:
                        gpus.append(parts[0])
        except Exception:
            pass

    _GPU_NAMES_CACHE = gpus or ["Card đồ họa tích hợp / Tiêu chuẩn"]
    return list(_GPU_NAMES_CACHE)


def test_ffmpeg_encoder(encoder: str) -> bool:
    """Run a 1-frame null encode with FFmpeg using DEVNULL stdio so a hung GPU driver
    can NEVER deadlock Python's subprocess reader threads on Windows.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    proc = None
    try:
        proc = subprocess.Popen(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "quiet",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=128x128:d=0.04",
                "-frames:v",
                "1",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        proc.wait(timeout=1.8)
        return proc.returncode == 0
    except Exception:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        return False


def probe_working_encoders(force_refresh: bool = False) -> dict[str, list[str]]:
    """Probe which GPU and CPU encoders work on this machine for h264, h265, av1, vp9.
    - Filters hardware encoder families by actual GPU vendor present on the system.
    - Caches results in memory and in `youtube_desktop_downloader_data/encoder_cache.json`.
    """
    global _ENCODER_CACHE
    with _ENCODER_CACHE_LOCK:
        if _ENCODER_CACHE is not None and not force_refresh:
            return _ENCODER_CACHE

        candidates_by_codec = {
            "h264": ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
            "h265": ["hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"],
            "av1": ["av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1"],
            "vp9": ["vp9_qsv", "libvpx-vp9"],
        }
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {k: [] for k in candidates_by_codec}

        gpu_list = _detect_gpu_names()
        gpu_blob = " ".join(gpu_list).lower()
        has_nvidia = "nvidia" in gpu_blob or "geforce" in gpu_blob or "quadro" in gpu_blob or "rtx" in gpu_blob or "gtx" in gpu_blob or bool(shutil.which("nvidia-smi"))
        has_intel = "intel" in gpu_blob or "iris" in gpu_blob or "uhd" in gpu_blob or "arc" in gpu_blob
        has_amd = "amd" in gpu_blob or "radeon" in gpu_blob

        cache_file = app_data_dir() / "encoder_cache.json"
        cache_sig = f"{ffmpeg}|{gpu_blob}"
        if not force_refresh and cache_file.is_file():
            try:
                cached_obj = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached_obj, dict) and cached_obj.get("sig") == cache_sig:
                    encs = cached_obj.get("encoders")
                    if isinstance(encs, dict) and all(k in encs for k in candidates_by_codec):
                        _ENCODER_CACHE = encs
                        return encs
            except Exception:
                pass

        dead_families: set[str] = set()
        if not has_nvidia:
            dead_families.add("nvenc")
        if not has_intel:
            dead_families.add("qsv")
        if not has_amd:
            dead_families.add("amf")

        result: dict[str, list[str]] = {}
        for codec, enc_list in candidates_by_codec.items():
            working: list[str] = []
            for enc in enc_list:
                if enc.startswith("lib"):
                    working.append(enc)
                    continue
                family = enc.split("_")[-1]
                if family in dead_families:
                    continue
                if test_ffmpeg_encoder(enc):
                    working.append(enc)
                elif codec == "h264":
                    # If base H.264 hardware encoder for this vendor fails, skip higher codecs for this vendor
                    dead_families.add(family)
            result[codec] = working

        _ENCODER_CACHE = result
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"sig": cache_sig, "encoders": result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return result


class HardwareMonitor:
    """Collects static hardware profile and periodic live system metrics without blocking the UI thread."""

    def __init__(self):
        self._last_net_time = time.monotonic()
        self._last_net_recv = 0
        self._last_net_sent = 0
        self._has_nvidia_smi = bool(shutil.which("nvidia-smi"))
        self._cached_gpu_u: float | None = None
        self._cached_gpu_mem: float | None = None
        self._gpu_poll_busy = False
        self._last_gpu_poll = 0.0
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
                net = psutil.net_io_counters()
                if net:
                    self._last_net_recv = net.bytes_recv
                    self._last_net_sent = net.bytes_sent
            except Exception:
                pass

    def build_profile(self, probe_encoders: bool = True) -> HardwareProfile:
        cores = (psutil.cpu_count(logical=False) if psutil else None) or os.cpu_count() or 1
        threads = (psutil.cpu_count(logical=True) if psutil else None) or os.cpu_count() or 1
        ram_gb = 0.0
        if psutil is not None:
            try:
                ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
            except Exception:
                pass
        os_str = f"{platform.system()} {platform.release()} ({platform.machine()})"
        encoders = probe_working_encoders() if probe_encoders else {}
        return HardwareProfile(
            cpu_name=_detect_cpu_name(),
            cpu_cores=cores,
            cpu_threads=threads,
            gpu_names=_detect_gpu_names(),
            ram_total_gb=ram_gb,
            os_name=os_str,
            working_encoders=encoders,
        )

    def _trigger_async_gpu_poll(self) -> None:
        if not self._has_nvidia_smi or self._gpu_poll_busy:
            return
        now = time.monotonic()
        if now - self._last_gpu_poll < 2.5:
            return
        self._gpu_poll_busy = True
        self._last_gpu_poll = now

        def _worker():
            proc = None
            try:
                proc = subprocess.Popen(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,utilization.memory",
                        "--format=csv,noheader,nounits",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                out, _ = proc.communicate(timeout=1.5)
                if proc.returncode == 0 and out and out.strip():
                    first = out.strip().splitlines()[0]
                    parts = [p.strip() for p in first.split(",")]
                    self._cached_gpu_u = float(parts[0])
                    self._cached_gpu_mem = float(parts[1]) if len(parts) > 1 else None
            except Exception:
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            finally:
                self._gpu_poll_busy = False

        threading.Thread(target=_worker, daemon=True).start()

    def sample_metrics(self, download_dir: str = "") -> LiveMetrics:
        m = LiveMetrics()
        if psutil is not None:
            try:
                m.cpu_percent = float(psutil.cpu_percent(interval=None))
            except Exception:
                pass
            try:
                vm = psutil.virtual_memory()
                m.ram_percent = float(vm.percent)
                m.ram_used_gb = round(vm.used / (1024 ** 3), 1)
                m.ram_total_gb = round(vm.total / (1024 ** 3), 1)
            except Exception:
                pass
            try:
                now = time.monotonic()
                dt = max(0.1, now - self._last_net_time)
                net = psutil.net_io_counters()
                if net:
                    m.net_down_bps = max(0.0, (net.bytes_recv - self._last_net_recv) / dt)
                    m.net_up_bps = max(0.0, (net.bytes_sent - self._last_net_sent) / dt)
                    self._last_net_recv = net.bytes_recv
                    self._last_net_sent = net.bytes_sent
                    self._last_net_time = now
            except Exception:
                pass

        # Disk usage via shutil.disk_usage (works even without psutil)
        try:
            target = Path(download_dir).expanduser() if download_dir else Path.home()
            while not target.exists() and target.parent != target:
                target = target.parent
            usage = shutil.disk_usage(target if target.exists() else Path.anchor)
            m.disk_total_gb = round(usage.total / (1024 ** 3), 1)
            m.disk_free_gb = round(usage.free / (1024 ** 3), 1)
            m.disk_percent = round(100.0 * usage.used / usage.total, 1) if usage.total else 0.0
        except Exception:
            pass

        self._trigger_async_gpu_poll()
        m.gpu_percent = self._cached_gpu_u
        m.gpu_mem_percent = self._cached_gpu_mem
        return m
