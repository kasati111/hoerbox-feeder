"""ffmpeg audio pipeline + ID3 tagging.

Output: MP3, 128 kbit/s CBR, 44.1 kHz, mono or stereo (user-configurable via
the Setup page, see Settings.audio_channels), two-pass loudnorm to -16 LUFS,
leading silence trimmed. ID3 tags and cover art are set with mutagen.
"""
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from mutagen.id3 import APIC, ID3, TALB, TIT2, TRCK
from mutagen.id3 import error as id3_error
from mutagen.mp3 import MP3

from . import config

logger = logging.getLogger("hoerbox.audio")

_HEARTBEAT_INTERVAL = 30  # seconds


def _run(
    cmd: list,
    timeout: Optional[float] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess with a hard wall-clock timeout, calling `heartbeat`
    (if given) roughly every _HEARTBEAT_INTERVAL seconds while it runs.

    Without the timeout, a wedged ffmpeg/ffprobe (e.g. reading a corrupted
    or partial input) blocks forever — Python can't force-kill the single
    worker thread from outside, so this is the only real fix for that class
    of stuck job, as opposed to the watchdog (worker.check_stuck_jobs),
    which can only correct the database bookkeeping around an already-stuck
    call, not un-stick it.

    The heartbeat exists because that same watchdog keys off Job.updated_at
    to decide "stuck" — and a long-but-healthy ffmpeg run (timeouts here can
    legitimately reach several hours for long content, see
    _ffmpeg_timeout()) doesn't otherwise touch the database at all while
    it's running. Without a heartbeat, the watchdog would misidentify a
    perfectly healthy multi-hour encode as stuck partway through. Uses
    Popen + polling (rather than subprocess.run's own timeout) specifically
    to get a callback in between.
    """
    logger.debug("run: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.monotonic()
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=_HEARTBEAT_INTERVAL)
                return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if heartbeat is not None:
                    try:
                        heartbeat()
                    except Exception:  # noqa: BLE001
                        logger.warning("heartbeat callback failed", exc_info=True)
                if timeout is not None and time.monotonic() - start > timeout:
                    proc.kill()
                    proc.communicate()
                    logger.error("command timed out after %ss: %s", timeout, " ".join(cmd))
                    raise RuntimeError("Die Aufbereitung des Tons hat zu lange gedauert.") from None
    finally:
        if proc.poll() is None:
            proc.kill()


def _ffmpeg_timeout(duration_seconds: Optional[int]) -> int:
    """Scale the ffmpeg timeout to the input's own length.

    A fixed timeout would either false-positive on long content (a 3h
    audiobook chapter can legitimately take a while on slow/loaded
    hardware) or leave short clips waiting far longer than any real hang
    would need to surface. 3x real-time is generous even for a loaded
    Raspberry Pi doing audio-only encode+loudnorm (no video, typically much
    faster than real-time). Capped at 12h — high enough that it only ever
    kicks in for an implausible duration value (corrupted metadata, not a
    real episode), rather than clipping the safety margin for genuinely
    long content: a real 3h audiobook chapter needs up to 9h of budget at
    3x, so the cap has to clear that with room to spare, not sit near it.
    Unknown duration falls back to a flat hour rather than a short value
    that would kill long content whose length just wasn't reported.
    """
    if not duration_seconds:
        return 3600
    return min(43200, max(300, duration_seconds * 3))


def _loudnorm_measure(
    input_path: Path, timeout: int, heartbeat: Optional[Callable[[], None]] = None
) -> Optional[dict]:
    """First loudnorm pass: measure the input to get correction parameters."""
    af = (
        f"loudnorm=I={config.LOUDNORM_I}:TP={config.LOUDNORM_TP}:"
        f"LRA={config.LOUDNORM_LRA}:print_format=json"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(input_path),
        "-af", af, "-f", "null", "-",
    ]
    proc = _run(cmd, timeout=timeout, heartbeat=heartbeat)
    output = proc.stderr
    # loudnorm prints a JSON blob at the end of stderr.
    start = output.rfind("{")
    end = output.rfind("}")
    if start == -1 or end == -1 or end < start:
        logger.warning("loudnorm measure returned no JSON; falling back")
        return None
    try:
        return json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None


def process_audio(
    input_path: Path,
    output_path: Path,
    title: str,
    album: str,
    track: int,
    cover_path: Optional[Path] = None,
    duration_seconds: Optional[int] = None,
    heartbeat: Optional[Callable[[], None]] = None,
    channels: int = config.AUDIO_CHANNELS,
) -> Path:
    """Run the full ffmpeg pipeline and write the tagged MP3 to output_path.

    duration_seconds (from the source's own metadata, when known) scales
    the ffmpeg timeout — see _ffmpeg_timeout(). heartbeat, if given, is
    invoked periodically while ffmpeg runs so the stuck-job watchdog
    doesn't misidentify a long-but-healthy encode as stuck — see _run().
    channels (1=mono, 2=stereo) is caller-supplied rather than read from
    config directly, since it's a live, user-editable setting (Setup page)
    rather than a fixed deployment constant — see crud.Settings.audio_channels.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = _ffmpeg_timeout(duration_seconds)

    measured = _loudnorm_measure(input_path, timeout, heartbeat)

    # Build the second-pass loudnorm filter (linear, using measured values).
    if measured:
        loudnorm = (
            f"loudnorm=I={config.LOUDNORM_I}:TP={config.LOUDNORM_TP}:"
            f"LRA={config.LOUDNORM_LRA}:"
            f"measured_I={measured.get('input_i')}:"
            f"measured_TP={measured.get('input_tp')}:"
            f"measured_LRA={measured.get('input_lra')}:"
            f"measured_thresh={measured.get('input_thresh')}:"
            f"offset={measured.get('target_offset')}:linear=true:print_format=summary"
        )
    else:
        loudnorm = (
            f"loudnorm=I={config.LOUDNORM_I}:TP={config.LOUDNORM_TP}:"
            f"LRA={config.LOUDNORM_LRA}"
        )

    # Trim leading silence, then normalise loudness.
    # The aresample step between the two filters works around an ffmpeg 7.1.x
    # filtergraph bug ("Assertion best_input >= 0 failed") that some inputs
    # (e.g. Opus streams with a negative start_time from pre-skip padding)
    # trigger when silenceremove feeds directly into loudnorm.
    silence = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1"
    af = f"{silence},aresample=async=1,{loudnorm}"

    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-y",
        "-i", str(input_path),
        "-af", af,
        "-ac", str(channels),
        "-ar", str(config.AUDIO_SAMPLE_RATE),  # 44.1 kHz
        "-c:a", "libmp3lame",
        "-b:a", config.AUDIO_BITRATE,          # 128k CBR
        "-map_metadata", "-1",
        str(output_path),
    ]
    proc = _run(cmd, timeout=timeout, heartbeat=heartbeat)
    if proc.returncode != 0 or not output_path.exists():
        logger.error("ffmpeg failed: %s", proc.stderr[-1000:])
        raise RuntimeError("Die Aufbereitung des Tons ist fehlgeschlagen.")

    _write_tags(output_path, title, album, track, cover_path)
    return output_path


def _write_tags(
    path: Path, title: str, album: str, track: int, cover_path: Optional[Path]
) -> None:
    """Set ID3 tags and embed cover art with mutagen."""
    try:
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TALB(encoding=3, text=album))
        tags.add(TRCK(encoding=3, text=str(track)))
        if cover_path and cover_path.exists():
            mime = "image/jpeg"
            if cover_path.suffix.lower() == ".png":
                mime = "image/png"
            with open(cover_path, "rb") as fh:
                tags.add(
                    APIC(
                        encoding=3,
                        mime=mime,
                        type=3,  # front cover
                        desc="Cover",
                        data=fh.read(),
                    )
                )
        audio.save()
    except id3_error as exc:  # pragma: no cover
        logger.warning("Could not write ID3 tags: %s", exc)


def get_duration_seconds(path: Path) -> Optional[int]:
    """Read duration via ffprobe. Duration is non-critical metadata, so a
    timed-out/failed probe falls back to mutagen instead of failing the job."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    try:
        proc = _run(cmd, timeout=30)
        data = json.loads(proc.stdout)
        return int(float(data["format"]["duration"]))
    except (RuntimeError, json.JSONDecodeError, KeyError, ValueError):
        try:
            return int(MP3(str(path)).info.length)
        except Exception:
            return None
