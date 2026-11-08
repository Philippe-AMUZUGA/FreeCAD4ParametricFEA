"""Compare les resultats de l'etude `cantilever_full.json` a la solution analytique de la console.

Poutre encastree-libre, section b x h, longueur L, effort P au bout (theorie d'Euler-Bernoulli) :
    fleche en bout           delta = 4 P L^3 / (E b h^3)      (+ cisaillement : delta_s = 1.2 P L / (G b h))
    contrainte normale en x  sigma(x, y_fibre) = 6 P (L - x) / (b h^2)   (fibre extreme)
    cisaillement moyen sur la section : tau_m = P / (b h) ; la membrane lue sur la ligne de mi-largeur
    en differe (le cisaillement n'est pas uniforme en largeur) : elle est affichee pour information.
Usage : python validate_cantilever.py RES_full/results.csv
"""
import csv
import math
import sys

E, NU = 210000.0, 0.3
G = E / (2 * (1 + NU))


def main(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows or any(not r["status"].startswith("ok") for r in rows):
        print("etude vide ou en echec")
        return 1
    print("%3s %5s %5s %5s | %-26s | %-26s | %-26s | %-22s" % (
        "cas", "L", "h", "P", "fleche max  MEF / analyt", "Sxx(L/2,top) MEF / analyt",
        "Pb Tresca MEF / analyt", "Pm Tresca (info)"))
    worst = 0.0
    for r in rows:
        L, h, b, P = (float(r[k]) for k in ("L", "h", "b", "P"))
        d_an = 4 * P * L ** 3 / (E * b * h ** 3) + 1.2 * P * L / (G * b * h)
        s_an = 3 * P * L / (b * h ** 2)
        pm_an = 2 * P / (b * h)
        d, s = float(r["U_max_mm"]), float(r["Ptop_Sxx_MPa"])
        # flexion pure a mi-longueur : Tresca de Pb = |sigma_b| (cisaillement nul sur la partie lineaire)
        pb, pm = float(r["SCL_Pb_Tresca_MPa"]), float(r["SCL_Pm_Tresca_MPa"])
        errs = [abs(d / d_an - 1), abs(s / s_an - 1), abs(pb / s_an - 1)]   # Pm : information seulement (ligne de mi-largeur)
        worst = max(worst, max(errs))
        print("%3s %5.0f %5.0f %5.0f | %8.5f / %8.5f %+5.1f%% | %8.2f / %8.2f %+5.1f%% | "
              "%8.2f / %8.2f %+5.1f%% | %6.2f / %6.2f %+5.1f%%" % (
                  r.get("", r.get("status", "")), L, h, P, d, d_an, 100 * (d / d_an - 1), s, s_an,
                  100 * (s / s_an - 1), pb, s_an, 100 * (pb / s_an - 1), pm, pm_an,
                  100 * (pm / pm_an - 1)))
    print("ecart relatif maximal : %.2f %%" % (100 * worst))
    return 0 if worst == worst and worst < 0.05 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
