"""Recherche automatique de FreeCAD (executable en ligne de commande), quelle que soit la version.

Ordre de recherche :
 1. l'argument explicite (chemin d'un executable, d'un dossier `bin` ou racine d'installation, ou commande complete) ;
 2. les variables d'environnement F4PFEA_FREECADCMD puis FREECADCMD / FREECAD_BIN / FREECAD_PATH ;
 3. le PATH (freecadcmd, FreeCADCmd, freecad-cmd) ;
 4. les dossiers d'installation usuels (Windows, macOS, Linux, conda, AppImage extrait, snap) ;
 5. si plusieurs installations sont trouvees, la plus recente (version lue en interrogeant FreeCAD).
"""
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ENV_VARS = ("F4PFEA_FREECADCMD", "FREECADCMD", "FREECAD_BIN", "FREECAD_PATH")
EXE_NAMES = ("freecadcmd", "FreeCADCmd", "freecad-cmd", "FreeCADCmd.exe", "freecadcmd.exe")
_PROBE = "import FreeCAD as A\nprint('F4PFEA_VERSION', '.'.join(A.Version()[:3]))\n"


class FreeCADInstall(object):
    def __init__(self, command, version=None, origin=""):
        self.command = list(command)      # ex. ['C:/.../freecadcmd.exe']
        self.version = version            # ex. '1.1.4' ou None si non sondee
        self.origin = origin

    @property
    def bin_dir(self):
        p = self.command[0]
        return os.path.dirname(p) if os.path.sep in p or "/" in p else ""

    def __repr__(self):
        return "FreeCADInstall(%s, version=%s, via %s)" % (" ".join(self.command), self.version,
                                                           self.origin)


def _exe_in(folder):
    for n in EXE_NAMES:
        p = os.path.join(folder, n)
        if os.path.isfile(p):
            return p
    return None


def _from_hint(hint):
    """Un indice -> liste de commande ou None."""
    if not hint:
        return None
    hint = os.path.expandvars(os.path.expanduser(str(hint).strip().strip('"')))
    if os.path.isfile(hint):
        return [hint]
    if os.path.isdir(hint):
        for sub in ("", "bin", os.path.join("Contents", "Resources", "bin"),
                    os.path.join("usr", "bin")):
            p = _exe_in(os.path.join(hint, sub))
            if p:
                return [p]
    parts = shlex.split(hint, posix=(os.name != "nt"))
    if parts and (os.path.isfile(parts[0]) or shutil.which(parts[0])):
        return parts          # commande complete (AppImage, flatpak, wrapper)
    return None


def _standard_dirs():
    out = []
    if os.name == "nt":
        roots = [os.environ.get("LOCALAPPDATA", "") + r"\Programs",
                 os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("USERPROFILE", "") + r"\AppData\Local",
                 r"C:\FreeCAD", r"C:\\"]
        for r in roots:
            out += glob.glob(os.path.join(r, "FreeCAD*"))
        out += glob.glob(os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "apps",
                                      "freecad", "*"))
    elif sys.platform == "darwin":
        out += glob.glob("/Applications/FreeCAD*.app") + glob.glob(
            os.path.expanduser("~/Applications/FreeCAD*.app"))
    else:
        out += ["/usr", "/usr/local", "/opt/freecad", "/snap/freecad/current/usr"]
        out += glob.glob("/usr/lib/freecad*") + glob.glob("/opt/FreeCAD*")
        out += glob.glob(os.path.expanduser("~/FreeCAD*")) + glob.glob(
            os.path.expanduser("~/squashfs-root"))
    for var in ("CONDA_PREFIX", "VIRTUAL_ENV", "MAMBA_ROOT_PREFIX"):
        if os.environ.get(var):
            out.append(os.environ[var])
    return [d for d in out if os.path.isdir(d)]


def candidates(hint=None):
    """Generateur de (commande, origine) sans doublon."""
    seen = set()

    def emit(cmd, origin):
        key = tuple(cmd)
        if cmd and key not in seen:
            seen.add(key)
            return (cmd, origin)
        return None

    items = []
    if hint:
        items.append((_from_hint(hint), "argument"))
    for v in ENV_VARS:
        if os.environ.get(v):
            items.append((_from_hint(os.environ[v]), "variable " + v))
    for n in EXE_NAMES[:3]:
        p = shutil.which(n)
        if p:
            items.append(([p], "PATH"))
    for d in _standard_dirs():
        c = _from_hint(d)
        if c:
            items.append((c, "installation usuelle"))
    for cmd, origin in items:
        r = emit(cmd, origin) if cmd else None
        if r:
            yield r


def probe_version(command, timeout=120):
    """Interroge FreeCAD (script minimal) ; retourne '1.1.4' ou None."""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="f4pfea_probe_")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(_PROBE)
        r = subprocess.run(list(command) + [path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, universal_newlines=True)
        m = re.search(r"F4PFEA_VERSION\s+(\d+(?:\.\d+)*)", r.stdout or "")
        return m.group(1) if m else None
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")) or (0,)


def find_freecad(hint=None, probe=True):
    """Retourne la FreeCADInstall la plus appropriee ; leve FileNotFoundError avec la marche a suivre."""
    found = []
    if hint and not _from_hint(hint):
        raise FileNotFoundError("FreeCAD indique mais introuvable : %s" % hint)
    for cmd, origin in candidates(hint):
        found.append(FreeCADInstall(cmd, None, origin))
        if hint and origin == "argument":
            break
        if origin.startswith("variable") or origin == "PATH":
            break      # un choix explicite de l'utilisateur prime sur l'inventaire
    if not found:
        raise FileNotFoundError(
            "FreeCAD introuvable. Installer FreeCAD (>= 0.19) puis soit l'ajouter au PATH, soit "
            "definir la variable d'environnement F4PFEA_FREECADCMD (chemin de freecadcmd), soit "
            "passer freecad=... a la configuration.")
    if probe:
        good = []
        for inst in found:
            inst.version = probe_version(inst.command)
            if inst.version:
                good.append(inst)
        if good:
            found = sorted(good, key=lambda i: version_tuple(i.version), reverse=True)
        elif hint or any(i.origin.startswith("variable") for i in found):
            raise FileNotFoundError("FreeCAD indique mais inutilisable : %s" % found[0])
    return found[0]


def find_tool(name, install=None):
    """Chemin d'un utilitaire livre avec FreeCAD (ccx, gmsh) ou present dans le PATH ; None sinon."""
    exe = name + (".exe" if os.name == "nt" else "")
    if install and install.bin_dir:
        p = os.path.join(install.bin_dir, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name)
