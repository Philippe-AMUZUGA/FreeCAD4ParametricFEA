"""Figures (matplotlib, facultatif) : profil de linearisation, resultats d'un plan d'experiences."""
import csv
import os


def _mpl():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        raise ImportError("les figures demandent matplotlib : pip install freecad4parametricfea[full]")


def read_profile(csv_path):
    with open(csv_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {k: [float(r[k]) for r in rows] for k in rows[0]}


def plot_linearization(csv_path, png_path=None, title=None, equivalent="vonMises"):
    """Contrainte equivalente le long du segment : totale, membrane, membrane + flexion, pic."""
    plt = _mpl()
    d = read_profile(csv_path)
    s = d["s_mm"]
    key = "Tresca" if equivalent.lower() == "tresca" else "vonMises"
    fig, ax = plt.subplots(figsize=(5.2, 3.4), dpi=150)
    ax.plot(s, d["total_" + key], "-", color="#1f3a5f", lw=2, label="contrainte totale")
    if key == "vonMises":
        ax.plot(s, d["Sm_vonMises"], "--", color="#d98324", lw=1.5, label=r"membrane $P_m$")
        ax.plot(s, d["SmSb_vonMises"], "-.", color="#2e8b57", lw=1.5, label=r"membrane + flexion")
    else:
        ax.plot(s, d["Sm_Tresca"], "--", color="#d98324", lw=1.5, label=r"membrane $P_m$")
        ax.plot(s, d["SmSb_Tresca"], "-.", color="#2e8b57", lw=1.5, label=r"membrane + flexion")
    ax.set_xlabel("abscisse le long du segment (mm)")
    ax.set_ylabel("contrainte équivalente %s (MPa)" % ("de Tresca" if key == "Tresca" else "de von Mises"))
    ax.grid(alpha=.3)
    ax.legend(frameon=False, fontsize=8)
    if title:
        ax.set_title(title, fontsize=9)
    fig.tight_layout()
    png_path = png_path or os.path.splitext(csv_path)[0] + ".png"
    fig.savefig(png_path)
    plt.close(fig)
    return png_path


def plot_doe(rows, x, y, png_path, color=None):
    """Nuage de points d'un plan : sortie `y` en fonction de l'entree `x`."""
    plt = _mpl()
    ok = [r for r in rows if str(r.get("status", "")).startswith("ok") and r.get(x) is not None
          and r.get(y) is not None]
    fig, ax = plt.subplots(figsize=(5, 3.4), dpi=150)
    sc = ax.scatter([float(r[x]) for r in ok], [float(r[y]) for r in ok],
                    c=[float(r[color]) for r in ok] if color else "#1f3a5f", cmap="viridis", s=22)
    if color:
        fig.colorbar(sc, ax=ax, label=color)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)
    return png_path


def boundary_triangles(conn):
    """Triangles de peau d'un maillage de tetraedres (faces appartenant a un seul element)."""
    import numpy as np
    c = np.asarray(conn)[:, :4]
    faces = np.concatenate([c[:, [0, 1, 2]], c[:, [0, 1, 3]], c[:, [0, 2, 3]], c[:, [1, 2, 3]]])
    key = np.sort(faces, axis=1)
    _, idx, cnt = np.unique(key, axis=0, return_index=True, return_counts=True)
    return faces[idx[cnt == 1]]


def plot_field_3d(case_dir, field="vonMises", png_path=None, deform_scale=0.0, elev=22, azim=-62,
                  title=None, cmap="turbo", unit="MPa"):
    """Carte d'un champ nodal sur la peau de la piece (matplotlib, sans FreeCAD).

    deform_scale : facteur d'amplification des deplacements (0 = geometrie initiale).
    """
    import numpy as np
    plt = _mpl()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from .extract import CaseFields
    cf = CaseFields(case_dir)
    tri = boundary_triangles(cf.d["conn"])
    xyz = cf.xyz + deform_scale * cf.d["disp"]
    val = cf.node_scalar(field)
    polys = xyz[tri]
    col = val[tri].mean(axis=1)
    fig = plt.figure(figsize=(5.6, 4.0), dpi=160)
    ax = fig.add_subplot(111, projection="3d")
    pc = Poly3DCollection(polys, cmap=cmap, linewidths=0.0, edgecolors="none")
    pc.set_array(col)
    pc.set_clim(float(val.min()), float(val.max()))
    ax.add_collection3d(pc)
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(tuple(np.maximum(hi - lo, 1e-9)))
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)"); ax.set_zlabel("z (mm)")
    cb = fig.colorbar(pc, ax=ax, shrink=0.65, pad=0.14)
    cb.set_label("%s (%s)" % (field, unit) if unit else field)
    if title:
        ax.set_title(title, fontsize=9)
    fig.tight_layout()
    png_path = png_path or os.path.join(case_dir, "field_%s.png" % field)
    fig.savefig(png_path)
    plt.close(fig)
    return png_path
