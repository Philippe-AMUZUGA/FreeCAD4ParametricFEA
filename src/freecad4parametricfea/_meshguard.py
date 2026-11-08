"""Garde-fous du maillage et messages d'echec du solveur (Python pur, sans FreeCAD).

Le module est importe par `_worker.py` (execute dans FreeCAD) et par les tests : il ne depend de rien.
"""

TET_FACTOR = 8.5       # tetraedre regulier : volume d'un element = h^3 / TET_FACTOR


def estimate_elements(volume, h):
    """Nombre d'elements d'un volume maille a la taille h (tetraedres reguliers)."""
    return int(volume / (h ** 3 / TET_FACTOR)) if h and h > 0 else 0


def refined_extra_elements(area, size_refined, h_global, depth_factor=3.0):
    """Elements supplementaires dus a un raffinement local sur des faces d'aire `area` (mm2).

    Hypothese : une couche de epaisseur `depth_factor * size_refined` (plafonnee a h_global) est maillee a
    `size_refined` au lieu de h_global. Estimation grossiere, par exces de prudence plutot que par defaut."""
    if not size_refined or size_refined <= 0 or size_refined >= h_global:
        return 0
    depth = min(depth_factor * size_refined, h_global)
    vol = area * depth
    return max(0, estimate_elements(vol, size_refined) - estimate_elements(vol, h_global))


class MeshTooLarge(RuntimeError):
    pass


def check_mesh_size(n_real, max_elements, mode="error"):
    """Controle apres maillage. mode : 'error' (defaut) leve MeshTooLarge, 'warn' retourne un avertissement,
    'ignore' ne fait rien. Retourne un texte d'avertissement ou None."""
    if not max_elements or n_real is None or n_real <= max_elements:
        return None
    msg = ("le maillage compte %d elements, au-dela de mesh.max_elements = %d (zones raffinees comprises) : "
           "augmenter mesh.size_factor ou mesh.size, alleger les raffinements, ou relever mesh.max_elements"
           % (n_real, max_elements))
    mode = (mode or "error").lower()
    if mode == "ignore":
        return None
    if mode == "warn":
        return msg
    raise MeshTooLarge(msg + " (mesh.on_exceed = \"warn\" pour calculer quand meme)")


def solver_failure_message(n_nodes=None, n_elements=None, tail=None):
    """Message explicite quand CalculiX ne rend aucun resultat (processus tue, memoire, maillage trop lourd)."""
    size = ""
    if n_elements or n_nodes:
        size = " (maillage de %s elements, %s noeuds)" % (n_elements or "?", n_nodes or "?")
    msg = ("le solveur n'a produit aucun resultat%s. Causes les plus frequentes : memoire insuffisante "
           "(CalculiX interrompu par le systeme), trop d'elements, jacobien negatif ou maillage invalide, "
           "modele sans appui suffisant. Essayer un maillage plus grossier (mesh.size_factor), moins d'elements "
           "(mesh.max_elements), ou lire le dossier ccx/ du cas." % size)
    if tail:
        msg += " Derniere sortie du solveur : " + " | ".join(str(t).strip() for t in tail if str(t).strip())
    return msg
