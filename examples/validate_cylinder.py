"""Compare la linearisation radiale d'une virole sous pression a la solution de Lame (deformation plane).

    A = p Ri^2 / (Re^2 - Ri^2) ;  sr = A (1 - Re^2/r^2) ;  st = A (1 + Re^2/r^2) ;  sz = 2 nu A
Le segment va de Ri a Re. Equilibre exact : membrane circonferentielle = p Ri / (Re - Ri).
Usage : python validate_cylinder.py RES_cyl/results.csv
"""
import csv
import sys
import numpy as np

NU = 0.3


def lame(p, ri, re, n=4001):
    r = np.linspace(ri, re, n)
    A = p * ri ** 2 / (re ** 2 - ri ** 2)
    sr, st = A * (1 - re ** 2 / r ** 2), A * (1 + re ** 2 / r ** 2)
    sz = np.full_like(r, 2 * NU * A)
    t = re - ri
    integ = lambda y: np.trapezoid(y, r) if hasattr(np, "trapezoid") else np.trapz(y, r)
    m = {k: integ(v) / t for k, v in (("r", sr), ("t", st), ("z", sz))}
    b = {k: 6 / t ** 2 * integ(v * (t / 2 - (r - ri))) for k, v in (("r", sr), ("t", st), ("z", sz))}
    tres = lambda a, c, d: max(a, c, d) - min(a, c, d)
    return {"Pm_tt": m["r"], "Pm_aa": m["z"], "Pm_bb": m["t"], "Pb_bb": b["t"],
            "Pm_Tresca": tres(m["r"], m["t"], m["z"]),
            "PmPb_start_Tresca": tres(m["r"] + b["r"], m["t"] + b["t"], m["z"] + b["z"]),
            "max_vm": float(np.max(np.sqrt(0.5 * ((sr - st) ** 2 + (st - sz) ** 2 + (sz - sr) ** 2)))),
            "hoop_equilibre": p * ri / t}


def main(path):
    worst = 0
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows or any(not r["status"].startswith("ok") for r in rows):
        print("etude vide ou en echec")
        return 1
    for r in rows:
        ri, re, p = float(r["Ri"]), float(r["Re"]), float(r["p"])
        a = lame(p, ri, re)
        pairs = [("Pm_tt", "SCL_Pm_tt_MPa"), ("Pm_bb", "SCL_Pm_bb_MPa"), ("Pm_aa", "SCL_Pm_aa_MPa"),
                 ("Pm_Tresca", "SCL_Pm_Tresca_MPa"), ("PmPb_start_Tresca", "SCL_PmPb_start_Tresca_MPa"),
                 ("max_vm", "vonMises_max_MPa")]
        print("Ri=%g Re=%g p=%g  (equilibre p*Ri/t = %.4f MPa)" % (ri, re, p, a["hoop_equilibre"]))
        for k, c in pairs:
            m = float(r[c])
            e = abs(m - a[k]) / max(abs(a[k]), 1e-9)
            worst = max(worst, e)
            print("   %-18s MEF %9.4f   Lame %9.4f   ecart %5.2f %%" % (k, m, a[k], 100 * e))
    print("ecart relatif maximal : %.2f %%" % (100 * worst))
    return 0 if worst == worst and worst < 0.03 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
