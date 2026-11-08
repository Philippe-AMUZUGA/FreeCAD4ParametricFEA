"""Pilote d'une etude parametrique : plan -> calculs FreeCAD isoles -> extraction -> tableaux.

Chaque cas est calcule dans un processus FreeCAD distinct (freecadcmd) : un plantage du noyau
geometrique ou du mailleur ne perd que ce cas ; les calculs peuvent tourner en parallele ; le
pilote lui-meme n'a besoin ni de FreeCAD ni de sa version de Python.
"""
import concurrent.futures as cf
import csv
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time

from . import doe as DOE
from . import extract as EX
from .config import Config
from .locate import find_freecad

__version__ = "0.2.0"

log = logging.getLogger("freecad4parametricfea")
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_worker.py")
STATUS_COLS = ["status", "error", "warnings", "n_nodes", "n_elements", "mesh_size_mm", "time_s"]


def _jsonable(v):
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except ImportError:
        pass
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class Case(object):
    def __init__(self, index, row):
        self.index = index
        self.row = row                # colonnes du plan, telles que fournies
        self.params = {}              # cible -> valeur (appliquees au modele)
        self.values = {}              # alias/nom -> valeur numerique (pour les expressions)
        self.mesh_override = {}       # surcharge de mesh.* propre au cas
        self.dir = None
        self.salt = ""                # empreinte du modele et du maillage (fixee par l'etude)

    @property
    def key(self):
        blob = json.dumps([self.params, self.mesh_override, self.salt], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


class Study(object):
    def __init__(self, config, freecad=None, reextract_only=False):
        """reextract_only : etude destinee a `reextract` seul ; `model` est alors facultatif (aucun modele n'est
        ouvert) et seuls doe, variables, outputs et run.output_dir sont necessaires."""
        self.cfg = Config.from_any(config, require_model=not reextract_only)
        self.reextract_only = reextract_only
        self.model = self.cfg.path(self.cfg["model"]) if self.cfg.get("model") else None
        if not reextract_only and not os.path.isfile(self.model):
            raise FileNotFoundError("modele introuvable : %s" % self.model)
        self.out_dir = self.cfg.path(self.cfg["run"]["output_dir"])
        self._install = freecad
        self.plan_columns = []
        self.cases = []
        self.source_xlsx = None
        self._lock = threading.Lock()
        self._salt_cache = None

    # --------------------------------------------------------------------------- installation
    @property
    def install(self):
        if self._install is None:
            hint = self.cfg.get("freecad")
            self._install = find_freecad(self.cfg.path(hint) if hint and os.path.exists(
                self.cfg.path(hint)) else hint)
            log.info("FreeCAD : %s", self._install)
        return self._install

    # ------------------------------------------------------------------------------- le plan
    def build_cases(self):
        doe = self.cfg["doe"]
        variables = self.cfg["variables"]
        if doe["type"] == "from_cases":
            return self._cases_from_disk()
        if doe["type"] == "excel":
            path = self.cfg.path(doe["file"])
            cols, rows, sheet = DOE.read_excel_plan(path, doe.get("sheet"))
            self.source_xlsx = path
            self.plan_columns = cols
        elif doe["type"] == "full":
            rows = DOE.full_factorial(doe.get("levels") or {})
            self.plan_columns = list((doe.get("levels") or {}).keys())
        else:
            rows, self.plan_columns = [{}], []
        ignore = set(doe.get("ignore_columns") or [])
        cases = []
        for i, row in enumerate(rows):
            c = Case(i, row)
            for col, val in row.items():
                if col in ignore or val is None or str(col).startswith(("#", "_")):
                    continue
                if col.startswith("mesh."):
                    c.mesh_override[col[5:]] = _jsonable(val)
                    continue
                target = variables.get(col, col if "." in col else None)
                if target is None:
                    continue
                c.params[target] = _jsonable(val)
                if _is_number(val):
                    c.values[col] = float(val)
                    c.values[col.replace(".", "_")] = float(val)
            for alias, target in variables.items():
                if target in c.params and _is_number(c.params[target]):
                    c.values[alias] = float(c.params[target])
            c.salt = self._salt()
            cases.append(c)
        self.cases = cases
        unmapped = [col for col in self.plan_columns
                    if col not in variables and "." not in col and col not in ignore
                    and not col.startswith(("#", "_"))]
        if unmapped:
            raise ValueError(
                "colonnes du plan sans cible : %s. Les declarer dans `variables`, utiliser une cible "
                "'Objet.cle', ou les lister dans doe.ignore_columns" % unmapped)
        targets = {}
        for col in self.plan_columns:
            t = variables.get(col, col if "." in col else None)
            if t and not col.startswith("mesh.") and col not in ignore:
                if t in targets:
                    raise ValueError("les colonnes %s et %s visent la meme cible %s" % (targets[t], col, t))
                targets[t] = col
        if not cases:
            raise ValueError("le plan ne contient aucun cas")
        return cases

    def _cases_from_disk(self):
        """doe.type = from_cases : les cas sont lus dans <output_dir>/cases/*/case.json (plan et parametres
        enregistres au calcul) ; aucun plan, aucun modele, aucune variable a redonner."""
        root = os.path.join(self.out_dir, "cases")
        cases = []
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name, "case.json")
                if not (name.startswith("case_") and os.path.isfile(p)):
                    continue
                with open(p) as fh:
                    cj = json.load(fh)
                c = Case(int(cj["index"]), dict(cj.get("plan") or {}))
                c.params = dict(cj.get("params") or {})
                for k, v in c.row.items():
                    if _is_number(v):
                        c.values[k] = float(v)
                        c.values[k.replace(".", "_")] = float(v)
                cases.append(c)
        if not cases:
            raise ValueError("doe.type = from_cases : aucun cas calcule dans %s" % root)
        self.plan_columns = [k for k in cases[0].row if not str(k).startswith(("#", "_"))]
        self.cases = sorted(cases, key=lambda c: c.index)
        return self.cases

    def _salt(self):
        if self.model is None or not os.path.isfile(self.model):
            return ""                       # reextraction sans modele : la signature de reprise n'est pas utilisee
        if self._salt_cache is None:
            h = hashlib.sha1()
            with open(self.model, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if self.cfg.get("hook"):
                with open(self.cfg.path(self.cfg["hook"]), "rb") as fh:
                    h.update(fh.read())
            h.update(json.dumps([self.cfg["mesh"], self.cfg["materials"], self.cfg.get("analysis"),
                                 self.cfg.get("solver"), self.cfg["outputs"], __version__],
                                sort_keys=True, default=str).encode())
            self._salt_cache = h.hexdigest()[:12]
        return self._salt_cache

    # -------------------------------------------------------------------------- un cas isole
    def _job(self, case):
        c = self.cfg
        mesh = dict(c["mesh"])
        mesh.update(case.mesh_override)
        out = c["outputs"]
        ents = [{"name": e["name"], "object": e["object"], "subelement": e["subelement"]}
                for e in out.get("entities") or []]
        return {"model": self.model, "case_dir": case.dir, "case_id": case.index,
                "hook": self.cfg.path(c["hook"]) if c.get("hook") else None,
                "params": case.params, "values": case.values, "materials": c["materials"],
                "variables": c["variables"],
                "mesh": mesh, "analysis": c.get("analysis"), "solver": c.get("solver"),
                "entities": ents, "ccx_threads": c["run"]["ccx_threads"],
                "save_model": c["run"]["save_model"]}

    def _launch(self, job, job_path, log_path):
        env = dict(os.environ)
        env["F4PFEA_JOB"] = job_path
        tmpd = os.path.join(os.path.dirname(job_path), "tmp")
        os.makedirs(tmpd, exist_ok=True)
        for var in ("TMP", "TEMP", "TMPDIR"):
            env[var] = tmpd                       # un dossier temporaire par cas (parallelisme sur)
        cmd = list(self.install.command) + [WORKER]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x00000200          # CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        with open(log_path, "w") as lf:
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, **kw)
            try:
                p.wait(timeout=self.cfg["run"]["timeout_s"])
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                return "timeout"
        return p.returncode

    def run_case(self, case):
        t0 = time.time()
        case.dir = os.path.join(self.out_dir, "cases", "case_%04d" % case.index)
        os.makedirs(case.dir, exist_ok=True)
        meta_path = os.path.join(case.dir, "meta.json")
        if os.path.exists(meta_path):
            os.remove(meta_path)
        job = self._job(case)
        job_path = os.path.join(case.dir, "job.json")
        with open(job_path, "w") as fh:
            json.dump(job, fh, indent=1, default=str)
        rc = self._launch(job, job_path, os.path.join(case.dir, "freecad.log"))
        row = {"status": "error", "error": None}
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path) as fh:
                meta = json.load(fh)
            meta["index"] = case.index                      # rattachement du dossier au plan
            meta["config"] = self.config_number(case)
            meta["plan"] = {k: _jsonable(v) for k, v in case.row.items()}
            with open(meta_path, "w") as fh:
                json.dump(meta, fh, indent=1, default=str)
        if rc == "timeout":
            row["error"] = "depassement du delai (%s s)" % self.cfg["run"]["timeout_s"]
        elif meta.get("status") != "ok":
            row["error"] = meta.get("error") or "FreeCAD a ete interrompu (code %s), voir freecad.log" % rc
        else:
            try:
                vals, warns = EX.extract_case(case.dir, self.cfg["outputs"], case.values)
                row.update(vals)
                if self.cfg["run"]["plots"]:
                    warns += self._plots(case)
                row["status"] = "ok" if not warns else "partial"
                if warns:
                    row["error"] = "; ".join(warns)
            except Exception as exc:
                row["error"] = "extraction : %s" % exc
        if meta.get("warnings"):
            row["warnings"] = "; ".join(meta["warnings"])
        m = meta.get("mesh", {})
        row["n_nodes"] = m.get("nodes")
        row["n_elements"] = m.get("volumes") or m.get("faces")
        row["mesh_size_mm"] = m.get("size")
        row["time_s"] = round(time.time() - t0, 2)
        with open(os.path.join(case.dir, "case.json"), "w") as fh:
            json.dump({"index": case.index, "config": self.config_number(case), "row": row,
                       "params": case.params,
                       "plan": {k: _jsonable(v) for k, v in case.row.items()}}, fh, indent=1,
                      default=str)
        if not self.cfg["run"]["keep_fields"]:
            _rm(os.path.join(case.dir, "fields.npz"))
        shutil.rmtree(os.path.join(case.dir, "tmp"), ignore_errors=True)
        if not self.cfg["run"]["keep_solver_files"] and row["status"].startswith("ok"):
            shutil.rmtree(os.path.join(case.dir, "ccx"), ignore_errors=True)   # conserve pour diagnostic si echec
        return row

    def config_number(self, case):
        """Numero de configuration du plan (colonne `doe.config_column`, `Config` par defaut) ou None."""
        col = self.cfg["doe"].get("config_column") or "Config"
        v = _jsonable(case.row.get(col))
        return v

    def _plots(self, case):
        warns = []
        try:
            from . import plots
            for seg in self.cfg["outputs"].get("segments") or []:
                csvp = os.path.join(case.dir, "linearization_%s.csv" % seg["name"])
                if os.path.exists(csvp):
                    plots.plot_linearization(csvp, title="%s - cas %d" % (seg["name"], case.index))
        except Exception as exc:
            warns.append("figure : %s" % exc)
        return warns

    # ------------------------------------------------------------------------------ l'etude
    def run(self, progress=print):
        if self.reextract_only:
            raise RuntimeError("etude ouverte pour la reextraction seule : `run` demande la configuration complete")
        os.makedirs(self.out_dir, exist_ok=True)
        _setup_log(self.out_dir)
        lock, lock_path = _acquire_lock(self.out_dir)
        try:
            return self._run(progress)
        finally:
            lock.close()
            _rm(lock_path)

    def _run(self, progress):
        if not self.cases:
            self.build_cases()
        run = self.cfg["run"]
        done = self._load_done() if run["resume"] else {}
        results = {}
        todo = []
        for c in self.cases:
            if c.key in done:
                results[c.index] = done[c.key]
            else:
                todo.append(c)
        n = len(self.cases)
        progress("%d cas dont %d deja calcules ; FreeCAD %s" % (
            n, n - len(todo), self.install.version or "?"))
        count = [0]

        def work(case):
            try:
                row = self.run_case(case)
            except Exception as exc:                      # un cas ne doit jamais arreter l'etude
                row = {"status": "error", "error": "%s: %s" % (type(exc).__name__, exc),
                       "time_s": 0.0}
            with self._lock:
                results[case.index] = row
                count[0] += 1
                with open(os.path.join(self.out_dir, "results.jsonl"), "a") as fh:
                    fh.write(json.dumps({"key": case.key, "index": case.index,
                                         "config": self.config_number(case), "row": row},
                                        default=str) + "\n")
                progress("[%d/%d] cas %d : %s (%.1f s)%s" % (
                    count[0], len(todo), case.index, row["status"], row["time_s"],
                    "" if row["status"].startswith("ok") else " - " + str(row["error"])))
                if run["save_every"] and count[0] % run["save_every"] == 0:
                    self._write_tables(results)
            return row

        if run["workers"] > 1 and len(todo) > 1:
            with cf.ThreadPoolExecutor(run["workers"]) as ex:
                list(ex.map(work, todo))
        else:
            for c in todo:
                work(c)
        paths = self._write_tables(results)
        self.results = [self._merged(i, results[i]) for i in sorted(results)]
        self.output_files = paths
        ok = sum(1 for r in results.values() if str(r["status"]).startswith("ok"))
        progress("termine : %d/%d cas reussis -> %s" % (ok, n, paths.get("xlsx")))
        return self.results

    def _load_done(self):
        p = os.path.join(self.out_dir, "results.jsonl")
        done = {}
        if os.path.exists(p):
            with open(p) as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if str(d["row"].get("status", "")).startswith("ok"):
                        done[d["key"]] = d["row"]
        return done

    def _merged(self, index, row):
        c = self.cases[index]
        out = {k: _jsonable(v) for k, v in c.row.items() if v is not None or k in self.plan_columns}
        out.update(row)
        return out

    def _write_tables(self, results):
        rows = [self._merged(i, results[i]) for i in sorted(results)]
        out_cols = []
        for r in rows:
            for k in r:
                if k not in self.plan_columns and k not in out_cols and k not in STATUS_COLS:
                    out_cols.append(k)
        out_cols += STATUS_COLS
        paths = {}
        csv_path = os.path.join(self.out_dir, "results.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            cols = list(self.plan_columns) + out_cols
            w.writerow(cols)
            for r in rows:
                w.writerow([r.get(c, "") for c in cols])
        paths["csv"] = csv_path
        doe = self.cfg["doe"]
        base = os.path.splitext(os.path.basename(self.source_xlsx))[0] if self.source_xlsx else "plan"
        dest = os.path.join(self.out_dir, base + "_resultats.xlsx")
        try:
            paths["xlsx"] = DOE.write_results_excel(
                dest, self.plan_columns, out_cols, rows, source=self.source_xlsx,
                sheet=doe.get("result_sheet", "Resultats"), in_place=bool(doe.get("in_place")))
        except Exception as exc:
            log.error("ecriture du classeur impossible : %s", exc)
        return paths

    # ---------------------------------------------------------------- extraction sans recalcul
    def reextract(self, progress=print, out_dir=None):
        """Recalcule les sorties a partir des champs conserves (aucun appel a FreeCAD).

        out_dir : si fourni, les tableaux (results.csv, classeur) sont ecrits dans ce dossier, sur une COPIE
        du classeur du plan, et les resultats du calcul d'origine ne sont pas touches ; les champs sont
        lus dans le dossier de sortie de l'etude."""
        if not self.cases:
            self.build_cases()
        results = {}
        for c in self.cases:
            c.dir = os.path.join(self.out_dir, "cases", "case_%04d" % c.index)
            try:
                with open(os.path.join(c.dir, "case.json")) as fh:
                    cj = json.load(fh)
                old = cj["row"]
                if cj.get("params") != json.loads(json.dumps(c.params, default=str)):
                    raise ValueError("le plan a change depuis le calcul (cas %d) : relancer `run`" % c.index)
                vals, warns = EX.extract_case(c.dir, self.cfg["outputs"], c.values)
                row = {k: old.get(k) for k in STATUS_COLS}
                row.update(vals)
                row["status"] = "ok" if not warns else "partial"
                row["error"] = "; ".join(warns) or None
            except Exception as exc:
                row = {"status": "error", "error": "reextraction : %s" % exc}
            results[c.index] = row
        if out_dir:
            fields_dir, in_place = self.out_dir, self.cfg["doe"].get("in_place")
            self.out_dir = self.cfg.path(out_dir)
            os.makedirs(self.out_dir, exist_ok=True)
            self.cfg["doe"]["in_place"] = False
            try:
                paths = self._write_tables(results)
            finally:
                self.out_dir, self.cfg["doe"]["in_place"] = fields_dir, in_place
        else:
            paths = self._write_tables(results)
        self.results = [self._merged(i, results[i]) for i in sorted(results)]
        progress("reextraction terminee -> %s" % paths.get("xlsx"))
        return self.results


def _acquire_lock(out_dir):
    """Verrou entre processus : deux etudes ne partagent jamais le meme dossier de sortie."""
    path = os.path.join(out_dir, ".f4pfea.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - os.path.getmtime(path)
        if age < 6 * 3600:
            raise RuntimeError("une autre etude utilise deja %s (supprimer %s si ce n'est plus le cas)"
                               % (out_dir, path))
        os.remove(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    fh = os.fdopen(fd, "w")
    fh.write(str(os.getpid()))
    fh.flush()
    return fh, path


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            p.wait(timeout=30)
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        p.kill()


def _setup_log(out_dir):
    if any(isinstance(h, logging.FileHandler) for h in log.handlers):
        return
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(os.path.join(out_dir, "freecad4parametricfea.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    if not log.handlers or len(log.handlers) == 1:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.WARNING)
        log.addHandler(sh)


def inspect_model(model, freecad=None, workdir=None):
    """Liste les parametres modifiables et les objets FEM d'un modele (necessite FreeCAD)."""
    import tempfile
    inst = freecad or find_freecad()
    workdir = workdir or tempfile.mkdtemp(prefix="f4pfea_inspect_")
    job = {"model": os.path.abspath(model), "case_dir": workdir, "mode": "inspect"}
    jp = os.path.join(workdir, "job.json")
    with open(jp, "w") as fh:
        json.dump(job, fh)
    env = dict(os.environ)
    env["F4PFEA_JOB"] = jp
    subprocess.run(list(inst.command) + [WORKER], env=env, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=600)
    with open(os.path.join(workdir, "meta.json")) as fh:
        return json.load(fh)
