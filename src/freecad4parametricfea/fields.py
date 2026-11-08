"""Grandeurs derivees des tenseurs de contraintes et de deformations (numpy seul).

Convention de stockage : tenseur symetrique en 6 composantes, ordre (xx, yy, zz, xy, yz, xz).
"""
import numpy as np

COMPONENTS = ("xx", "yy", "zz", "xy", "yz", "xz")


def to_matrix(t):
    """(..., 6) -> (..., 3, 3)."""
    t = np.asarray(t, dtype=float)
    m = np.empty(t.shape[:-1] + (3, 3))
    m[..., 0, 0] = t[..., 0]
    m[..., 1, 1] = t[..., 1]
    m[..., 2, 2] = t[..., 2]
    m[..., 0, 1] = m[..., 1, 0] = t[..., 3]
    m[..., 1, 2] = m[..., 2, 1] = t[..., 4]
    m[..., 0, 2] = m[..., 2, 0] = t[..., 5]
    return m


def principal(t):
    """Valeurs principales triees S1 >= S2 >= S3, forme (..., 3)."""
    w = np.linalg.eigvalsh(to_matrix(t))
    return w[..., ::-1]


def von_mises(t):
    t = np.asarray(t, dtype=float)
    sxx, syy, szz, sxy, syz, sxz = (t[..., i] for i in range(6))
    return np.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy ** 2 + syz ** 2 + sxz ** 2)
    )


def tresca(t):
    """Contrainte equivalente de Tresca = S1 - S3 (= 2 x cission maximale)."""
    p = principal(t)
    return p[..., 0] - p[..., 2]


def equivalent_strain(e, nu):
    """Deformation equivalente de von Mises (deformations tensorielles).

    eps_eq = sqrt(2/3 e_ij e_ij) ramenee a nu = 0,5 par le facteur 1/(1+nu) usuel :
    eps_eq = 1/(1+nu) * sqrt(0.5*((exx-eyy)^2+(eyy-ezz)^2+(ezz-exx)^2) + 3*(exy^2+eyz^2+exz^2)).
    Elle est egale a vonMises / E en elasticite lineaire isotrope.
    """
    e = np.asarray(e, dtype=float)
    exx, eyy, ezz, exy, eyz, exz = (e[..., i] for i in range(6))
    core = np.sqrt(0.5 * ((exx - eyy) ** 2 + (eyy - ezz) ** 2 + (ezz - exx) ** 2)
                   + 3.0 * (exy ** 2 + eyz ** 2 + exz ** 2))
    return core / (1.0 + nu)


def stress_to_strain(s, young, nu):
    """Loi de Hooke isotrope (deformations tensorielles)."""
    s = np.asarray(s, dtype=float)
    tr = s[..., 0] + s[..., 1] + s[..., 2]
    out = np.empty_like(s)
    for i in range(3):
        out[..., i] = ((1 + nu) * s[..., i] - nu * tr) / young
    for i in range(3, 6):
        out[..., i] = (1 + nu) * s[..., i] / young
    return out


def scalar_field(name, tensor, nu=0.3):
    """Valeur scalaire d'une grandeur nommee a partir d'un tenseur (..., 6)."""
    n = name.lower()
    if n in ("vonmises", "mises", "von_mises", "seq"):
        return von_mises(tensor)
    if n == "tresca":
        return tresca(tensor)
    if n in ("s1", "maxprincipal", "principalmax"):
        return principal(tensor)[..., 0]
    if n in ("s3", "minprincipal", "principalmin"):
        return principal(tensor)[..., 2]
    if n in ("eps_vm", "strain_vm", "equivalentstrain"):
        return equivalent_strain(tensor, nu)
    if n[:1] in ("s", "e") and n[1:] in COMPONENTS:
        return np.asarray(tensor)[..., COMPONENTS.index(n[1:])]
    raise KeyError("grandeur inconnue : %s" % name)
