"""Live view of the images SerialEM acquires.

SerialEM accepts a single external connection, owned by the autoscreen process,
so the web server cannot ask it for images. Instead SerialEM is told to share
every new image in memory (its SaveNewImageToShrMem property) and to start a
watcher script on its own computer. The watcher turns each shared image into a
JPEG in a folder under the microscope's scope_path, where the web server reads
it. See interfaces/serialem_scripts/SmartScopeLiveImage.ps1.
"""
import logging
import re
import time
from pathlib import Path, PureWindowsPath
from typing import List, Optional

from django.core.cache import cache

logger = logging.getLogger(__name__)

DIRECTORY = 'live_view'
FRAMES_DIRECTORY = 'live'
WATCHER = 'SmartScopeLiveImage.bat'
SOURCES_FILE = 'live_sources.txt'
FRAME_NAME = re.compile(r'^frame_\d+\.jpg$')
WATCHER_FILES = Path(__file__).parent / 'interfaces' / 'serialem_scripts'

# The watcher rewrites its heartbeat every 5 s.
WATCHER_TIMEOUT = 30
CLOCK_WINDOW = 60
CLOCK_CACHE_TIMEOUT = 7 * 24 * 3600


def watcher_directory(scope_path: str) -> Path:
    return Path(scope_path, DIRECTORY)


def frames_directory(scope_path: str) -> Path:
    return watcher_directory(scope_path) / FRAMES_DIRECTORY


def install_watcher(scope_path: str, windows_path: str, list_directories: List[str]) -> str:
    """Puts the watcher on the share and returns the Windows path that starts it.

    list_directories: Windows directories where SerialEM may write its image list.
    """
    directory = watcher_directory(scope_path)
    directory.mkdir(parents=True, exist_ok=True)
    for source in sorted(WATCHER_FILES.iterdir()):
        (directory / source.name).write_bytes(source.read_bytes())
    sources = list(dict.fromkeys(d for d in list_directories if d))
    (directory / SOURCES_FILE).write_text(''.join(f'{d}\r\n' for d in sources), newline='')
    return str(PureWindowsPath(windows_path, DIRECTORY, WATCHER))


def _clock_key(microscope_id: str) -> str:
    return f'live_view_clock_{microscope_id}'


def _heartbeat_age(microscope_id: str, mtime: float) -> Optional[float]:
    """Seconds since the watcher last wrote its heartbeat, or None until that can be told.

    The file is stamped by the SerialEM computer, whose clock is not synchronised
    with this server, so the offset between the two is learned: it is the
    smallest lag seen, first trusted once the file is seen changing.
    """
    key = _clock_key(microscope_id)
    now = time.time()
    lag = now - mtime
    seen = cache.get(key) or {}
    offset = seen.get('offset')
    changing = seen.get('mtime') not in (None, mtime) and now - seen.get('seen', 0) < CLOCK_WINDOW
    if offset is not None and lag < offset:
        offset = lag
    elif changing and (offset is None or lag - offset > CLOCK_WINDOW):
        # The second case is the SerialEM computer's clock having been set back.
        offset = lag
    cache.set(key, dict(offset=offset, mtime=mtime, seen=now), timeout=CLOCK_CACHE_TIMEOUT)
    return None if offset is None else lag - offset


def read_frames(microscope_id: str, scope_path: str) -> Optional[dict]:
    """Images published by the watcher, oldest first, or None if it never ran.

    age: seconds since the newest image, None while the clock offset is unknown.
    running: whether the watcher is alive, None while that cannot be told.
    """
    directory = frames_directory(scope_path)
    try:
        heartbeat = (directory / 'heartbeat.txt').stat().st_mtime
    except OSError:
        return None
    frames, written = [], None
    try:
        written = (directory / 'index.txt').stat().st_mtime
        lines = (directory / 'index.txt').read_text(errors='replace').splitlines()
    except OSError:
        lines = []
    for line in lines:
        fields = line.split()
        if len(fields) < 7 or not FRAME_NAME.match(fields[1]):
            continue
        try:
            source_width, pixel_size = int(fields[4]), float(fields[6])
            frames.append(dict(
                sequence=int(fields[0]),
                file=fields[1],
                source_width=source_width,
                source_height=int(fields[5]),
                pixel_size_A=pixel_size or None,
                field_of_view_um=source_width * pixel_size / 10000 if pixel_size else None,
            ))
        except ValueError:
            continue
    heartbeat_age = _heartbeat_age(microscope_id, heartbeat)
    age = None
    if heartbeat_age is not None and written is not None:
        # Both files are stamped by the same computer, so the offset applies to both.
        age = max(0, heartbeat_age + heartbeat - written)
    return dict(
        frames=frames,
        age=age,
        running=None if heartbeat_age is None else heartbeat_age < WATCHER_TIMEOUT,
    )


def frame_file(scope_path: str, name: str) -> Optional[Path]:
    if not FRAME_NAME.match(name):
        return None
    frame = frames_directory(scope_path) / name
    return frame if frame.is_file() else None

