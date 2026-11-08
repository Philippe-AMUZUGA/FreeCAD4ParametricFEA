"""Interpolation d'un champ nodal en un point quelconque d'un maillage tetraedrique (TET4 / TET10)."""
import numpy as np

_EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]


class TetSampler:
    """Localise des points dans un maillage de tetraedres et interpole des champs nodaux.

    xyz   : (n, 3) coordonnees des noeuds
    conn  : (m, 4) ou (m, 10) indices (base 0) de noeuds par element
    """

    def __init__(self, xyz, conn):
        self.xyz = np.asarray(xyz, dtype=float)
        self.conn = np.asarray(conn, dtype=int)
        if self.conn.ndim != 2 or self.conn.shape[1] not in (4, 10):
            raise ValueError("elements tetraedriques TET4 ou TET10 attendus")
        self.corners = self.conn[:, :4]
        self.quadratic = self.conn.shape[1] == 10
        c = self.xyz[self.corners]                      # (m, 4, 3)
        self.centroid = c.mean(axis=1)
        a = c[:, 1:, :] - c[:, :1, :]                   # (m, 3, 3) lignes = aretes
        self.p0 = c[:, 0, :]
        self.inv = np.linalg.inv(np.transpose(a, (0, 2, 1)))
        self._tree = None
        try:
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.centroid)
        except Exception:
            self._tree = None
        self.mid_map = self._detect_mid_nodes() if self.quadratic else None
        self.curved = False
        if self.quadratic:
            self.curved = not self._mid_nodes_straight()      # noeuds milieux deplaces (CAO courbe)

    def _detect_mid_nodes(self):
        """Associe chaque noeud milieu (5 a 10) a son arete, par la geometrie."""
        k = min(self.conn.shape[0], 50)
        mid = self.xyz[self.conn[:k, 4:]]
        c = self.xyz[self.corners[:k]]
        cand = np.stack([(c[:, i] + c[:, j]) / 2 for i, j in _EDGES], axis=1)
        d = np.linalg.norm(mid[:, :, None, :] - cand[:, None, :, :], axis=3)
        pick = d.argmin(axis=2)
        ref = pick[0]
        if sorted(ref.tolist()) != list(range(6)) or not np.all(pick == ref[None, :]):
            raise ValueError("numerotation TET10 non reconnue")
        return ref

    def _mid_nodes_straight(self, tol=1e-3):
        """Vrai si, dans tous les elements, chaque noeud milieu est au milieu de son arete."""
        c = self.xyz[self.corners]
        mids = self.xyz[self.conn[:, 4:]]
        cand = np.stack([(c[:, i] + c[:, j]) / 2 for i, j in _EDGES], axis=1)
        exp = cand[:, self.mid_map, :]
        err = np.linalg.norm(mids - exp, axis=2).max(axis=1)
        size = np.linalg.norm(c[:, 1] - c[:, 0], axis=1)
        return bool(np.all(err <= tol * size))

    def _candidates(self, p, k=48):
        if self._tree is not None:
            _, idx = self._tree.query(p, k=min(k, self.conn.shape[0]))
            return np.atleast_1d(idx)
        d = np.linalg.norm(self.centroid - p, axis=1)
        return np.argsort(d)[:k]

    def locate(self, p):
        """Retourne (element, lambda[4], ecart). ecart = 0 si le point est dans l'element, sinon
        la plus forte coordonnee barycentrique negative en valeur absolue."""
        p = np.asarray(p, dtype=float)
        best = None
        for idx in (self._candidates(p), np.arange(self.conn.shape[0])):
            lam3 = np.einsum("kij,kj->ki", self.inv[idx], p - self.p0[idx])
            lam = np.concatenate([1.0 - lam3.sum(axis=1, keepdims=True), lam3], axis=1)
            worst = -lam.min(axis=1)
            j = int(worst.argmin())
            best = (int(idx[j]), lam[j], float(max(worst[j], 0.0)))
            if worst[j] < 1e-9:
                break
        if self.curved:                          # element courbe : inversion isoparametrique
            e, lam, _ = best
            lam = self._newton(e, lam, p)
            best = (e, lam, float(max(-lam.min(), 0.0)))
        return best

    def _newton(self, e, lam, p, iters=12):
        """Resout sum_i N_i(lam) x_i = p dans l'element e (10 noeuds, aretes courbes)."""
        X = self.xyz[self.conn[e]]
        lam = np.array(lam, dtype=float)
        for _ in range(iters):
            r = self.shape_functions(lam) @ X - p
            if np.linalg.norm(r) < 1e-12 * (1.0 + np.linalg.norm(p)):
                break
            J = np.empty((3, 3))
            for k in range(3):                   # derivee par rapport a lam[k+1] (lam[0] = 1 - somme)
                d = 1e-6
                lp, lm = lam.copy(), lam.copy()
                lp[k + 1] += d; lp[0] -= d
                lm[k + 1] -= d; lm[0] += d
                J[:, k] = (self.shape_functions(lp) - self.shape_functions(lm)) @ X / (2 * d)
            try:
                step = np.linalg.solve(J, -r)
            except np.linalg.LinAlgError:
                break
            lam[1:] += step
            lam[0] = 1.0 - lam[1:].sum()
        return lam

    def shape_functions(self, lam):
        if not self.quadratic:
            return lam
        n = np.empty(10)
        for i in range(4):
            n[i] = lam[i] * (2 * lam[i] - 1)
        for a in range(6):
            i, j = _EDGES[self.mid_map[a]]
            n[4 + a] = 4 * lam[i] * lam[j]
        return n

    def sample(self, points, fields):
        """points (q, 3) ; fields : dict nom -> (n_noeuds, ...). Retourne (dict, ecarts)."""
        points = np.atleast_2d(points)
        out = {k: [] for k in fields}
        gaps = []
        for p in points:
            e, lam, gap = self.locate(p)
            if gap > 0:   # point legerement hors maillage (arrondi) : on ramene dans l'element
                lam = np.clip(lam, 0, None)
                lam = lam / lam.sum()
            nf = self.shape_functions(lam)
            nodes = self.conn[e]
            for k, v in fields.items():
                out[k].append(np.tensordot(nf, np.asarray(v)[nodes], axes=(0, 0)))
            gaps.append(gap)
        return {k: np.array(v) for k, v in out.items()}, np.array(gaps)
