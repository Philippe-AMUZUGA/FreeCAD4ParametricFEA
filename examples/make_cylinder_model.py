"""Virole cylindrique (quart, symetries) sous pression interne : cas de Lame.

Lancement : freecadcmd make_cylinder_model.py  -> cylinder.FCStd
Parametres : CylOut.Radius (Re), CylIn.Radius (Ri), CylOut.Height (Lz), ConstraintPressure.Pressure.
Conditions : symetrie sur x = 0 et y = 0, deformation plane (uz = 0) sur les deux fonds.
Solution analytique (deformation plane) : voir validate_cylinder.py
"""
import os
import FreeCAD as App
import Part
import ObjectsFem

here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
out = os.path.join(here, "cylinder.FCStd")
RI, RE, LZ, P0 = 100.0, 120.0, 40.0, 10.0

doc = App.newDocument("Cylinder")
co = doc.addObject("Part::Cylinder", "CylOut"); co.Radius = RE; co.Height = LZ
ci = doc.addObject("Part::Cylinder", "CylIn"); ci.Radius = RI
ci.setExpression("Height", "CylOut.Height")
box = doc.addObject("Part::Box", "Quadrant")
box.setExpression("Length", "CylOut.Radius*2"); box.setExpression("Width", "CylOut.Radius*2")
box.setExpression("Height", "CylOut.Height")
cut = doc.addObject("Part::Cut", "Ring"); cut.Base = co; cut.Tool = ci
com = doc.addObject("Part::MultiCommon", "Virole"); com.Shapes = [cut, box]
doc.recompute()
sh = com.Shape
print("VOL", sh.Volume, "faces", len(sh.Faces))

def face(pred):
    for i, f in enumerate(sh.Faces, 1):
        if pred(f):
            return "Face%d" % i
fx0 = face(lambda f: abs(f.CenterOfMass.x) < 1e-6 and abs(f.normalAt(0, 0).x) > .99)
fy0 = face(lambda f: abs(f.CenterOfMass.y) < 1e-6 and abs(f.normalAt(0, 0).y) > .99)
fz0 = face(lambda f: abs(f.CenterOfMass.z) < 1e-6)
fz1 = face(lambda f: abs(f.CenterOfMass.z - LZ) < 1e-6)
fin = face(lambda f: f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - RI) < 1e-6)
print("FACES", fx0, fy0, fz0, fz1, fin)

ana = ObjectsFem.makeAnalysis(doc, "Analysis")
mk = getattr(ObjectsFem, "makeSolverCalculiXCcxTools", None) or getattr(ObjectsFem, "makeSolverCalculixCcxTools")
solver = mk(doc, "SolverCcxTools"); solver.AnalysisType = "static"; ana.addObject(solver)
mat = ObjectsFem.makeMaterialSolid(doc, "MaterialSolid")
m = mat.Material
m["Name"] = "Steel-Generic"; m["YoungsModulus"] = "210000 MPa"; m["PoissonRatio"] = "0.3"; m["Density"] = "7800 kg/m^3"
mat.Material = m
ana.addObject(mat)
for nm, fc, flag in (("SymX", fx0, "x"), ("SymY", fy0, "y"), ("EndZ0", fz0, "z"), ("EndZ1", fz1, "z")):
    d = ObjectsFem.makeConstraintDisplacement(doc, nm)
    d.References = [(com, fc)]
    if hasattr(d, flag + "Fix"):          # FreeCAD < 0.20
        setattr(d, flag + "Fix", True)
    else:                                  # FreeCAD >= 0.20
        setattr(d, flag + "Free", False)
        setattr(d, flag + "Displacement", "0 mm")
    ana.addObject(d)
pr = ObjectsFem.makeConstraintPressure(doc, "ConstraintPressure")
pr.References = [(com, fin)]; pr.Pressure = "%g MPa" % P0; pr.Reversed = False
ana.addObject(pr)
mesh = ObjectsFem.makeMeshGmsh(doc, "FEMMeshGmsh"); mesh.Shape = com
mesh.CharacteristicLengthMax = "5 mm"; mesh.ElementOrder = "2nd"
ana.addObject(mesh)
doc.recompute()
doc.saveAs(out)
print("MODELE_ECRIT", out)
