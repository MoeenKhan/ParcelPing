"""Taking over the data folder and "Start with Windows" from the app's earlier name."""

import sys
import types

import pytest

from app import autostart, config


class FakeRunKey:
    """Stands in for HKCU\\...\\Run, so tests never touch the real registry."""

    def __init__(self, values):
        self.values = dict(values)

    def module(self):
        key = self

        class Handle:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def query(handle, name):
            if name not in key.values:
                raise FileNotFoundError(name)
            return key.values[name], 1

        def delete(handle, name):
            del key.values[name]

        def set_value(handle, name, reserved, kind, value):
            key.values[name] = value

        return types.SimpleNamespace(
            HKEY_CURRENT_USER=0, KEY_QUERY_VALUE=1, KEY_SET_VALUE=2, REG_SZ=1,
            OpenKey=lambda *a: Handle(), QueryValueEx=query, DeleteValue=delete, SetValueEx=set_value)


@pytest.fixture
def run_key(monkeypatch):
    key = FakeRunKey({"ParcelPing": r'"C:\Old\ParcelPing.exe" --minimized', "SomethingElse": "x"})
    monkeypatch.setitem(sys.modules, "winreg", key.module())
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\PingParcel.exe")
    monkeypatch.delenv("PINGPARCEL_DATA_DIR", raising=False)
    return key


def test_start_with_windows_moves_to_new_name(run_key):
    autostart.adopt_old_entry()
    assert run_key.values == {"PingParcel": r'"C:\Apps\PingParcel.exe" --minimized', "SomethingElse": "x"}


def test_start_with_windows_stays_off_if_it_was_off(run_key):
    del run_key.values["ParcelPing"]
    autostart.adopt_old_entry()
    assert run_key.values == {"SomethingElse": "x"}


def test_test_runs_never_touch_the_registry(run_key, monkeypatch):
    monkeypatch.setenv("PINGPARCEL_DATA_DIR", "somewhere")
    autostart.adopt_old_entry()
    assert "ParcelPing" in run_key.values and "PingParcel" not in run_key.values


def test_running_from_source_never_touches_the_registry(run_key, monkeypatch):
    monkeypatch.delattr(sys, "frozen")
    autostart.adopt_old_entry()
    assert "ParcelPing" in run_key.values and "PingParcel" not in run_key.values


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("PINGPARCEL_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(config, "is_portable", lambda: False)
    return tmp_path


def test_old_data_is_copied_over(appdata):
    old = appdata / "ParcelPing"
    old.mkdir()
    (old / "parcels.db").write_bytes(b"my parcels")

    d = config.data_dir()

    assert d == appdata / "PingParcel"
    assert (d / "parcels.db").read_bytes() == b"my parcels"
    assert (old / "parcels.db").exists()  # kept as a backup


def test_existing_new_data_is_left_alone(appdata):
    (appdata / "ParcelPing").mkdir()
    (appdata / "ParcelPing" / "parcels.db").write_bytes(b"old")
    (appdata / "PingParcel").mkdir()
    (appdata / "PingParcel" / "parcels.db").write_bytes(b"new")

    assert (config.data_dir() / "parcels.db").read_bytes() == b"new"


def test_fresh_install(appdata):
    d = config.data_dir()
    assert d == appdata / "PingParcel" and d.is_dir()
    assert list(d.iterdir()) == []
