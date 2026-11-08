import itertools

import numpy as np
import pytest

from freecad4parametricfea.sampling import TetSampler

EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]


def cube_tets(n=3, order=1, permute_mid=None):
    """Cube [0,1]^3 decoupe en n^3 hexaedres, chacun en 6 tetraedres (maillage conforme)."""
    g = np.linspace(0, 1, n + 1)
    pts, index = [], {}

    def nid(p):
        key = tuple(np.round(p, 12))
        if key not in index:
            index[key] = len(pts)
            pts.append(p)
        return index[key]

    corner_order = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    tets_local = [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]
    conn = []
    for i, j, k in itertools.product(range(n), repeat=3):
        hv = [np.array([g[i + a], g[j + b], g[k + c]]) for a, b, c in corner_order]
        for t in tets_local:
            c4 = [hv[v] for v in t]
            ids = [nid(p) for p in c4]
            if order == 2:
                mids = [nid((c4[a] + c4[b]) / 2) for a, b in EDGES]
                if permute_mid:
                    mids = [mids[m] for m in permute_mid]
                ids += mids
            conn.append(ids)
    return np.array(pts), np.array(conn)


def test_linear_field_exact_tet4():
    xyz, conn = cube_tets(3, 1)
    f = 2 * xyz[:, 0] - 3 * xyz[:, 1] + 0.5 * xyz[:, 2] + 7
    s = TetSampler(xyz, conn)
    q = np.array([[0.31, 0.77, 0.12], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.5, 0.5]])
    out, gap = s.sample(q, {"f": f})
    assert np.allclose(out["f"], 2 * q[:, 0] - 3 * q[:, 1] + 0.5 * q[:, 2] + 7, atol=1e-10)
    assert gap.max() < 1e-9


@pytest.mark.parametrize("perm", [None, (3, 4, 5, 0, 1, 2)])
def test_quadratic_field_exact_tet10(perm):
    """Le champ quadratique est reproduit exactement, meme si les noeuds milieux sont numerotes
    dans un autre ordre (l'ordre est detecte par la geometrie)."""
    xyz, conn = cube_tets(2, 2, permute_mid=perm)
    f = xyz[:, 0] ** 2 + xyz[:, 1] * xyz[:, 2] - 2 * xyz[:, 2] ** 2
    s = TetSampler(xyz, conn)
    q = np.array([[0.31, 0.77, 0.12], [0.9, 0.1, 0.45], [0.5, 0.0, 1.0]])
    out, _ = s.sample(q, {"f": f})
    ex = q[:, 0] ** 2 + q[:, 1] * q[:, 2] - 2 * q[:, 2] ** 2
    assert np.allclose(out["f"], ex, atol=1e-10)


def test_tensor_field_and_outside_point():
    xyz, conn = cube_tets(2, 1)
    T = np.tile(np.arange(6.0), (len(xyz), 1))
    s = TetSampler(xyz, conn)
    out, gap = s.sample(np.array([[0.4, 0.4, 0.4], [1.2, 0.5, 0.5]]), {"T": T})
    assert np.allclose(out["T"][0], np.arange(6.0))
    assert gap[1] > 0.1          # point hors maillage signale


def test_curved_tet10_nodal_values_reproduced():
    """Elements a noeuds milieux deplaces : la valeur en un point est inversee isoparametriquement."""
    xyz, conn = cube_tets(1, 2)
    rng = np.random.default_rng(3)
    xyz = xyz.copy()
    for e in conn[:, 4:].ravel():              # on deplace legerement les noeuds milieux
        xyz[e] += rng.normal(scale=0.01, size=3)
    f = xyz[:, 0] * 3 - xyz[:, 1] + 2
    s = TetSampler(xyz, conn)
    assert s.curved
    # un noeud milieu : la valeur interpolee doit retrouver exactement la valeur nodale
    node = conn[0, 6]
    out, gap = s.sample(xyz[node][None, :], {"f": f})
    assert out["f"][0] == pytest.approx(f[node], abs=1e-8) and gap[0] < 1e-6
