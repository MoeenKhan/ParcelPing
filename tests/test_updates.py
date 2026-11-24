"""Updater: release check, download verification and the in-place swap.

Uses a fake GitHub (no network) and dummy files instead of a real .exe.
"""

import hashlib
import subprocess

import pytest

from app import updates

PREFIX = "https://github.com/MoeenKhan/PingParcel/releases/download/"
GOOD_EXE = b"MZ" + b"\0" * (updates.MIN_SIZE + 10)


class FakeResponse:
    def __init__(self, status=200, body=b"", data=None, headers=None):
        self.status_code, self.content, self._data = status, body, data
        self.headers = headers or {}
        self.text = body.decode("latin-1")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    def __init__(self, routes):
        self.routes, self.requested = routes, []

    def get(self, url, **kw):
        self.requested.append(url)
        return self.routes.get(url) or FakeResponse(404)

    def close(self):
        pass


REPO = "https://github.com/MoeenKhan/PingParcel"


def latest_redirects_to(location, status=302):
    """github.com/<repo>/releases/latest answering with a redirect."""
    return FakeGitHub({f"{REPO}/releases/latest": FakeResponse(status, headers={"Location": location})})


# ---- checking --------------------------------------------------------------

@pytest.mark.parametrize("tag,current,newer", [
    ("v1.1.0", "1.0.0", True),
    ("v1.0.10", "1.0.9", True),
    ("v2.0.0", "1.9.9", True),
    ("v1.0.0", "1.0.0", False),
    ("v0.9.0", "1.0.0", False),
    ("", "1.0.0", False),
])
def test_is_newer(tag, current, newer):
    assert updates.is_newer(tag, current) is newer


def test_latest_release_newer():
    rel = updates.latest_release(latest_redirects_to(f"{REPO}/releases/tag/v9.9.9"))
    assert rel == updates.Release(
        "9.9.9", f"{REPO}/releases/tag/v9.9.9",
        f"{REPO}/releases/download/v9.9.9/PingParcel.exe",
        f"{REPO}/releases/download/v9.9.9/PingParcel.exe.sha256")


def test_latest_release_not_newer():
    assert updates.latest_release(latest_redirects_to(f"{REPO}/releases/tag/v0.0.1")) is None


def test_no_releases_yet():
    # Without releases, /releases/latest redirects to the (empty) releases list.
    assert updates.latest_release(latest_redirects_to(f"{REPO}/releases")) is None


@pytest.mark.parametrize("location", [
    "https://github.com/MoeenKhan/PingParcel/releases/tag/../../evil",
    "https://github.com/MoeenKhan/PingParcel/releases/tag/v9.9.9/../x",
    "https://example.com/somewhere-else",
    "",
])
def test_odd_redirects_ignored(location):
    assert updates.latest_release(latest_redirects_to(location)) is None


def test_other_sites_never_trusted():
    assert updates.latest_release(latest_redirects_to("https://example.com/x/y/releases/tag/v9.9.9")) is None


def test_follows_a_renamed_repo():
    # GitHub sends an old repo name's URLs on to the new name.
    new = "https://github.com/MoeenKhan/SomethingNew"
    gh = FakeGitHub({
        f"{REPO}/releases/latest": FakeResponse(301, headers={"Location": f"{new}/releases/latest"}),
        f"{new}/releases/latest": FakeResponse(302, headers={"Location": f"{new}/releases/tag/v9.9.9"}),
    })
    rel = updates.latest_release(gh)
    assert rel.version == "9.9.9"
    assert rel.exe_url == f"{new}/releases/download/v9.9.9/PingParcel.exe"
    assert rel.sha256_url == f"{new}/releases/download/v9.9.9/PingParcel.exe.sha256"


def test_relative_redirect():
    rel = updates.latest_release(latest_redirects_to("/MoeenKhan/PingParcel/releases/tag/v9.9.9"))
    assert rel.exe_url == f"{REPO}/releases/download/v9.9.9/PingParcel.exe"


def test_redirect_loop_gives_up():
    gh = FakeGitHub({f"{REPO}/releases/latest": FakeResponse(301, headers={"Location": f"{REPO}/releases/latest"})})
    assert updates.latest_release(gh) is None
    assert len(gh.requested) == 3


@pytest.mark.parametrize("status", [200, 404, 429, 500])
def test_no_redirect_means_no_update(status):
    assert updates.latest_release(latest_redirects_to(f"{REPO}/releases/tag/v9.9.9", status)) is None


# ---- downloading -----------------------------------------------------------

def _download(tmp_path, exe_bytes, sha_text):
    rel = updates.Release("9.9.9", "page", PREFIX + "exe", PREFIX + "sha")
    gh = FakeGitHub({PREFIX + "exe": FakeResponse(body=exe_bytes),
                     PREFIX + "sha": FakeResponse(body=sha_text.encode())})
    exe = tmp_path / "PingParcel.exe"
    exe.write_bytes(b"MZ current")
    return updates.download(rel, exe=exe, session=gh)


def test_download_verified(tmp_path):
    digest = hashlib.sha256(GOOD_EXE).hexdigest()
    new = _download(tmp_path, GOOD_EXE, f"{digest}  PingParcel.exe\n")
    assert new.name == "PingParcel.new.exe"
    assert new.read_bytes() == GOOD_EXE
    assert not (tmp_path / "PingParcel.exe.download").exists()


def test_download_checksum_mismatch_rejected(tmp_path):
    with pytest.raises(updates.UpdateError, match="checksum"):
        _download(tmp_path, GOOD_EXE, "0" * 64 + "  PingParcel.exe")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["PingParcel.exe"]


def test_download_not_a_program_rejected(tmp_path):
    page = b"<html>" + b"x" * updates.MIN_SIZE
    with pytest.raises(updates.UpdateError, match="Windows program"):
        _download(tmp_path, page, hashlib.sha256(page).hexdigest())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["PingParcel.exe"]


def test_download_missing_checksum_rejected(tmp_path):
    with pytest.raises(updates.UpdateError, match="checksum"):
        _download(tmp_path, GOOD_EXE, "not a checksum")


# ---- installing ------------------------------------------------------------

@pytest.fixture
def launches(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    return calls


def test_install_swaps_and_restarts(tmp_path, launches):
    exe = tmp_path / "PingParcel.exe"
    exe.write_bytes(b"old version")
    new = tmp_path / "PingParcel.new.exe"
    new.write_bytes(b"new version")

    updates.install(new, exe=exe, args=["--updated", "--minimized"])

    assert exe.read_bytes() == b"new version"
    assert (tmp_path / "PingParcel.old.exe").read_bytes() == b"old version"
    assert not new.exists()
    (args, kw), = launches
    assert args[0] == str(exe)
    assert args[1:3] == ["--updated", "--minimized"]
    assert args[3] == "--wait-pid"
    assert kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_install_failure_keeps_working_copy(tmp_path, launches):
    exe = tmp_path / "PingParcel.exe"
    exe.write_bytes(b"old version")
    missing = tmp_path / "PingParcel.new.exe"  # e.g. deleted by antivirus

    with pytest.raises(OSError):
        updates.install(missing, exe=exe)

    assert exe.read_bytes() == b"old version"
    assert not launches


def test_cleanup_removes_leftovers(tmp_path):
    exe = tmp_path / "PingParcel.exe"
    exe.write_bytes(b"current")
    for name in ("PingParcel.old.exe", "PingParcel.new.exe", "PingParcel.exe.download"):
        (tmp_path / name).write_bytes(b"leftover")
    updates.cleanup(exe)
    import time
    for _ in range(50):
        if sorted(p.name for p in tmp_path.iterdir()) == ["PingParcel.exe"]:
            break
        time.sleep(0.05)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["PingParcel.exe"]


def test_not_frozen_never_self_updates():
    rel = updates.Release("9.9.9", "page", PREFIX + "exe", PREFIX + "sha")
    assert updates.current_exe() is None  # tests run from source
    assert not updates.can_self_update(rel)
