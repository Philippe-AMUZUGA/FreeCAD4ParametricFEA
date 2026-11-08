"""Plan d'experiences : plan complet, plan fourni dans un classeur Excel, ecriture des resultats.

Un plan est une liste de lignes ; chaque ligne est un dict {nom_de_colonne: valeur}.
"""
import itertools
import math
import os
import shutil

import numpy as np


# ------------------------------------------------------------------------------------ niveaux
def parse_levels(spec):
    """Niveaux d'un facteur : liste, scalaire, 'debut:fin:n', {start, stop, num|step}, {values}."""
    if isinstance(spec, dict):
        if "values" in spec:
            return list(spec["values"])
        a, b = float(spec["start"]), float(spec["stop"])
        if "num" in spec:
            return [float(x) for x in np.linspace(a, b, int(spec["num"]))]
        step = float(spec["step"])
        if step == 0 or (b - a) * step < 0:
            raise ValueError("pas incoherent avec les bornes : %r" % (spec,))
        n = int(math.floor((b - a) / step + 1e-9)) + 1
        return [a + i * step for i in range(n)]
    if isinstance(spec, str) and spec.count(":") == 2:
        a, b, n = spec.split(":")
        return [float(x) for x in np.linspace(float(a), float(b), int(n))]
    if isinstance(spec, (list, tuple)):
        return list(spec)
    return [spec]


def full_factorial(levels):
    """Plan complet : produit cartesien ; le dernier facteur varie le plus vite."""
    names = list(levels)
    grids = [parse_levels(levels[n]) for n in names]
    for n, g in zip(names, grids):
        if not g:
            raise ValueError("facteur %s : aucun niveau" % n)
    rows = [dict(zip(names, combo)) for combo in itertools.product(*grids)]
    if not rows:
        raise ValueError("plan vide")
    return rows


# ------------------------------------------------------------------------------------- Excel
def read_excel_plan(path, sheet=None):
    """Lit un plan dans un classeur. Retourne (colonnes, lignes, nom_de_feuille).

    La premiere ligne non vide contient les en-tetes. Les colonnes sans en-tete sont ignorees
    (colonne d'index d'un export pandas). La lecture s'arrete a la premiere ligne entierement vide.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    start = next((i for i, r in enumerate(rows) if any(c is not None for c in r)), None)
    if start is None:
        raise ValueError("feuille vide : %s" % path)
    header = rows[start]
    cols = [(j, str(h).strip()) for j, h in enumerate(header) if h is not None and str(h).strip()]
    if len({c for _, c in cols}) != len(cols):
        raise ValueError("en-tetes de colonnes en double dans le plan")
    out = []
    for r in rows[start + 1:]:
        if all(c is None for c in r):
            break
        out.append({name: r[j] if j < len(r) else None for j, name in cols})
    return [n for _, n in cols], out, ws.title


def _unique_sheet_name(wb, base):
    name, k = base[:31], 1
    while name in wb.sheetnames:
        k += 1
        name = "%s_%d" % (base[:27], k)
    return name


def write_results_excel(dest, plan_columns, out_columns, table, source=None, sheet="Resultats",
                        in_place=False):
    """Ecrit une feuille `sheet` : colonnes du plan recopiees puis colonnes de sortie.

    source : classeur d'origine. Si fourni, ses feuilles sont conservees intactes ; la feuille de
    resultats est AJOUTEE. in_place=False : on travaille sur une copie (`dest`). Retourne le chemin ecrit.
    """
    import openpyxl
    keep_vba = bool(source) and str(source).lower().endswith(".xlsm")
    if source:
        target = source if in_place else dest
        if not in_place:
            shutil.copyfile(source, dest)
        wb = openpyxl.load_workbook(target, keep_vba=keep_vba)
    else:
        target = dest
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
    ws = wb.create_sheet(_unique_sheet_name(wb, sheet))
    cols = list(plan_columns) + [c for c in out_columns if c not in plan_columns]
    ws.append(cols)
    for row in table:
        ws.append([_cell(row.get(c)) for c in cols])
    for r in ws.iter_rows(min_row=2):                  # un texte commencant par = reste un texte
        for c in r:
            if isinstance(c.value, str) and c.value[:1] in ("=", "+", "-", "@"):
                c.data_type = "s"
    ws.freeze_panes = "A2"
    for j, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = max(10, min(28, len(c) + 2))
    try:
        tmp = target + ".tmp"
        wb.save(tmp)
        os.replace(tmp, target)                        # remplacement atomique
    except PermissionError:
        alt = os.path.splitext(dest)[0] + "_copie" + os.path.splitext(dest)[1]
        wb.save(alt)
        return alt
    return target


def _cell(v):
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, float) and (v != v):       # NaN -> cellule vide
        return None
    if isinstance(v, (list, tuple, dict)):
        return str(v)
    return v


def write_template(path, levels):
    """Cree un classeur de plan vierge : en-tetes + une ligne par combinaison (plan complet)."""
    import openpyxl
    rows = full_factorial(levels)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plan"
    names = list(levels)
    ws.append(names)
    for r in rows:
        ws.append([r[n] for n in names])
    wb.save(path)
    return path
