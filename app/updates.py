"""Updates from GitHub releases: check, download, verify, swap in place.

For the built .exe:
1. latest_release() asks GitHub for the newest release.
2. download() saves its PingParcel.exe next to the running one, checks it
   against the release's published SHA-256 and that it is a Windows program,
   and only then names it PingParcel.new.exe.
3. install() renames the running .exe to PingParcel.old.exe (Windows allows
   renaming a running program, not overwriting it), moves the new one into its
   place and starts it. The new copy waits for this one to exit.
4. cleanup() on the next start deletes leftover .old/.new/.download files.

Running from source, or from a folder we can't write to, only the check runs
and the app links to the release page instead.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import __version__, config
from .core.carriers.base import new_session

ASSET_NAME = f"{config.APP_NAME}.exe"
MIN_SIZE = 5_000_000  # the real .exe is ~30 MB; anything tiny is an error page


def _repo_url() -> str:
    # Override for local end-to-end tests of the updater.
    return (os.environ.get("PINGPARCEL_UPDATE_REPO_URL")
            or f"https://github.com/{config.GITHUB_REPO}").rstrip("/")


# Paths in GitHub's redirects: a release tag, or a renamed repo's /releases/latest.
_TAG = re.compile(r"^/[\w.-]+/[\w.-]+/releases/tag/(v?\d+(?:\.\d+)*(?:-[0-9A-Za-z.]+)?)/?$")
_LATEST = re.compile(r"^/[\w.-]+/[\w.-]+/releases/latest/?$")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    exe_url: str = ""
    sha256_url: str = ""


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_newer(tag: str, current: str = __version__) -> bool:
    return bool(tag) and parse_version(tag) > parse_version(current)


def latest_release(session=None) -> Release | None:
    """The latest release if it's newer than this version, else None.

    Reads where github.com/<repo>/releases/latest redirects to, rather than
    calling the GitHub API: the API allows only 60 anonymous requests an hour
    per IP address, which a mobile network shared by many people (carrier
    NAT) can use up.
    """
    if not config.GITHUB_REPO:
        return None
    url = f"{_repo_url()}/releases/latest"
    host = urlsplit(url).netloc
    own = session is None
    session = session or new_session()
    try:
        # Follow a renamed repo (old/releases/latest -> new/releases/latest),
        # stopping at the redirect to the newest release's tag.
        for _ in range(3):
            r = session.get(url, allow_redirects=False, timeout=15, headers={"User-Agent": config.APP_NAME})
            if r.status_code not in (301, 302, 303, 307, 308):
                return None  # no releases yet, or GitHub unavailable
            location = urljoin(url, r.headers.get("Location", ""))
            if urlsplit(location).netloc != host:
                return None  # only ever this site
            m = _TAG.search(urlsplit(location).path)
            if m:
                break
            if not _LATEST.search(urlsplit(location).path):
                return None
            url = location
        else:
            return None
    finally:
        if own:
            session.close()
    tag = m.group(1)
    if not is_newer(tag):
        return None
    # The repo the tag belongs to (the new name, after a rename); files come from its releases.
    repo = location[:location.rindex("/releases/tag/")]
    download = f"{repo}/releases/download/{tag}/{ASSET_NAME}"
    return Release(tag.lstrip("v"), f"{repo}/releases/tag/{tag}", download, f"{download}.sha256")


# ---- self-update (built .exe only) ----------------------------------------------

def current_exe() -> Path | None:
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable).resolve()
    return None


def _paths(exe: Path) -> tuple[Path, Path, Path]:
    stem = exe.stem
    return (exe.with_name(f"{stem}.new.exe"), exe.with_name(f"{stem}.old.exe"),
            exe.with_name(f"{exe.name}.download"))


def can_self_update(release: Release, exe: Path | None = None) -> bool:
    exe = exe or current_exe()
    if exe is None or not (release.exe_url and release.sha256_url):
        return False
    try:  # can we write next to the .exe? (not e.g. in Program Files)
        fd, probe = tempfile.mkstemp(dir=exe.parent, prefix=".pp-write-test-")
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def download(release: Release, exe: Path | None = None, session=None) -> Path:
    """Download and verify the new .exe; returns its path (PingParcel.new.exe)."""
    exe = exe or current_exe()
    if exe is None:
        raise UpdateError("not running as an .exe")
    new, _, partial = _paths(exe)
    own = session is None
    session = session or new_session()
    try:
        r = session.get(release.sha256_url, timeout=30)
        r.raise_for_status()
        m = re.search(r"\b([0-9a-fA-F]{64})\b", r.text)
        if not m:
            raise UpdateError("the release has no valid checksum")
        expected = m.group(1).lower()

        digest, size, head = hashlib.sha256(), 0, b""
        with session.get(release.exe_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    if not head:
                        head = chunk[:2]
                    digest.update(chunk)
                    size += len(chunk)
                    f.write(chunk)
        if head != b"MZ" or size < MIN_SIZE:
            raise UpdateError("the download isn't a Windows program")
        if digest.hexdigest() != expected:
            raise UpdateError("the download doesn't match the release checksum")
        os.replace(partial, new)
        return new
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        if own:
            session.close()


def install(new: Path, exe: Path | None = None, args: list[str] | None = None) -> None:
    """Put the new .exe in place and start it. The caller should then quit."""
    exe = exe or current_exe()
    if exe is None:
        raise UpdateError("not running as an .exe")
    _, old, _ = _paths(exe)
    old.unlink(missing_ok=True)
    os.replace(exe, old)  # allowed while running
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)  # put the working copy back
        raise
    env = dict(os.environ)
    # Start as a fresh app, not as a child of this one-file .exe.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe), *(args or []), "--wait-pid", str(os.getpid())],
                     env=env, creationflags=flags, close_fds=True)


def cleanup(exe: Path | None = None) -> None:
    """Delete files left by an update, retrying while the old copy is exiting."""
    exe = exe or current_exe()
    if exe is None:
        return
    leftovers = [p for p in _paths(exe) if p.exists()]
    if not leftovers:
        return

    def run():
        for _ in range(30):
            for p in list(leftovers):
                try:
                    p.unlink(missing_ok=True)
                    leftovers.remove(p)
                except OSError:
                    pass  # still in use; try again shortly
            if not leftovers:
                return
            time.sleep(1)

    threading.Thread(target=run, daemon=True).start()


def wait_for_pid(pid: int, timeout: float = 20) -> None:
    """Wait for the previous copy to exit (Windows only)."""
    if sys.platform != "win32":
        return
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        kernel32.CloseHandle(handle)
