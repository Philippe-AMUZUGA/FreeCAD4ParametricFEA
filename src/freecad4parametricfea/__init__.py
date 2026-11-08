"""freecad4parametricfea : calculs par elements finis parametriques pilotes depuis FreeCAD.

Usage minimal ::

    from freecad4parametricfea import run
    results = run("etude.json")          # liste de dict : une ligne par cas du plan
"""
from .config import Config, DEFAULTS
from .runner import Study, inspect_model
from .locate import find_freecad

__version__ = "0.2.0"
__all__ = ["run", "Study", "Config", "DEFAULTS", "find_freecad", "inspect_model", "__version__"]


def run(config, freecad=None, progress=print):
    """Lance une etude complete (plan, calculs, extraction, classeur) et retourne les lignes de resultats."""
    return Study(config, freecad=freecad).run(progress=progress)
