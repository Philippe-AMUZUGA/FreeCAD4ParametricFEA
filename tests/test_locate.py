import os
import stat

import pytest

from freecad4parametricfea import locate


def _fake(tmp_path, name):
    p = tmp_path / "bin"
    p.mkdir()
    exe = p / (name + (".exe" if os.name == "nt" else ""))
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe), str(p)


def test_hint_file_and_folder(tmp_path):
    exe, folder = _fake(tmp_path, "freecadcmd")
    same = lambda got: [os.path.normcase(x) for x in got] == [os.path.normcase(exe)]
    assert same(locate._from_hint(exe))
    assert same(locate._from_hint(str(tmp_path)))               # racine d'installation
    assert same(locate._from_hint(folder))                      # dossier bin
    assert locate._from_hint(str(tmp_path / "rien")) is None


def test_env_variable_wins_over_search(tmp_path, monkeypatch):
    exe, _ = _fake(tmp_path, "freecadcmd")
    monkeypatch.setenv("F4PFEA_FREECADCMD", exe)
    inst = locate.find_freecad(probe=False)
    assert inst.command == [exe] and "F4PFEA" in inst.origin


def test_not_found_message(monkeypatch):
    for v in locate.ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(locate, "candidates", lambda hint=None: iter(()))
    with pytest.raises(FileNotFoundError, match="F4PFEA_FREECADCMD"):
        locate.find_freecad()


def test_version_tuple():
    assert locate.version_tuple("1.1.4") > locate.version_tuple("0.21.2") > locate.version_tuple("0.20")
