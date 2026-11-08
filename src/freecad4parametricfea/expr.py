"""Evaluation d'expressions numeriques simples (coordonnees, rayons) sans `eval`.

Exemples : "L/2", "xmax - 5", "b*0.5 + 1", "sqrt(L**2 + h**2)".
Seuls les operateurs + - * / **, les nombres, les noms fournis et quelques fonctions sont permis.
"""
import ast
import math

FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs,
         "min": min, "max": max, "radians": math.radians, "atan2": math.atan2}
CONSTS = {"pi": math.pi}


def evaluate(expr, names=None):
    names = names or {}
    if isinstance(expr, (int, float)):
        return float(expr)
    tree = ast.parse(str(expr).strip(), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b,
                   ast.Div: lambda: a / b, ast.Pow: lambda: a ** b}
            for k, f in ops.items():
                if isinstance(n.op, k):
                    return f()
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Name):
            if n.id in names:
                return float(names[n.id])
            if n.id in CONSTS:
                return CONSTS[n.id]
            raise ValueError("nom inconnu dans l'expression '%s' : %s" % (expr, n.id))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS:
            return float(FUNCS[n.func.id](*[ev(a) for a in n.args]))
        raise ValueError("expression non autorisee : %s" % expr)

    return ev(tree)


def point(coords, names=None):
    """Liste de 3 expressions -> [x, y, z] flottants."""
    if len(coords) != 3:
        raise ValueError("un point comporte 3 coordonnees : %r" % (coords,))
    return [evaluate(c, names) for c in coords]
