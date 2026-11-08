import json
import os

import openpyxl
import pytest

from freecad4parametricfea import doe, expr
from freecad4parametricfea.config import Config


def test_levels_and_full_factorial():
    assert doe.parse_levels("0:10:3") == [0.0, 5.0, 10.0]
    assert doe.parse_levels({"start": 1, "stop": 2, "step": 0.5}) == [1.0, 1.5, 2.0]
    assert doe.parse_levels(5) == [5]
    rows = doe.full_factorial({"a": [1, 2], "b": "0:1:3"})
    assert len(rows) == 6 and rows[0] == {"a": 1, "b": 0.0} and rows[1]["b"] == 0.5


def test_excel_roundtrip_keeps_other_sheets(tmp_path):
    src = tmp_path / "plan.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MonPlan"
    ws.append([None, "L", "h", "note"])
    ws.append([0, 100, 10, "x"])
    ws.append([1, 120, 12, "y"])
    ws.append([None, None, None, None])
    ws.append([9, 999, 99, "apres la ligne vide"])
    wb.create_sheet("Autre")["A1"] = "intact"
    wb.save(src)
    cols, rows, sheet = doe.read_excel_plan(str(src), "MonPlan")
    assert cols == ["L", "h", "note"] and len(rows) == 2 and sheet == "MonPlan"
    out = tmp_path / "out.xlsx"
    p = doe.write_results_excel(str(out), cols, ["vm"], [dict(r, vm=1.5) for r in rows], source=str(src))
    w2 = openpyxl.load_workbook(p)
    assert w2.sheetnames == ["MonPlan", "Autre", "Resultats"]
    assert w2["Autre"]["A1"].value == "intact"
    res = list(w2["Resultats"].iter_rows(values_only=True))
    assert res[0] == ("L", "h", "note", "vm") and res[1] == (100, 10, "x", 1.5)
    assert openpyxl.load_workbook(src).sheetnames == ["MonPlan", "Autre"]     # source non modifiee


def test_excel_in_place(tmp_path):
    src = tmp_path / "p.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a"])
    wb.active.append([1])
    wb.save(src)
    p = doe.write_results_excel(str(tmp_path / "x.xlsx"), ["a"], ["y"], [{"a": 1, "y": 2}],
                                source=str(src), in_place=True)
    assert p == str(src) and "Resultats" in openpyxl.load_workbook(src).sheetnames


def test_expression_evaluator_is_safe():
    assert expr.evaluate("L/2 + 1", {"L": 10}) == 6.0
    assert expr.evaluate("sqrt(a**2+b**2)", {"a": 3, "b": 4}) == 5.0
    for bad in ("__import__('os').system('x')", "L.real", "open('f')", "[1][0]", "lambda: 1"):
        with pytest.raises((ValueError, SyntaxError)):
            expr.evaluate(bad, {"L": 1})
    with pytest.raises(ValueError):
        expr.evaluate("inconnu*2", {})


def test_config_defaults_and_validation(tmp_path):
    cfg = Config.from_any({"model": "m.FCStd"})
    assert cfg["doe"]["type"] == "full" and cfg["mesh"]["size"] == "auto" and cfg["run"]["resume"]
    assert cfg["outputs"]["global"]["fields"][0] == "vonMises"
    with pytest.raises(ValueError):
        Config.from_any({})
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "mesh": {"order": "3rd"}})
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "doe": {"type": "excel"}})
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "outputs": {"segments": [{"name": "s", "p1": [0, 0, 0]}]}})
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"model": "sub/m.FCStd"}), encoding="utf-8")
    c = Config.from_any(str(p))
    assert c.path(c["model"]) == os.path.normpath(os.path.join(str(tmp_path), "sub", "m.FCStd"))
