"""Construit, dans FreeCAD, une console (poutre encastree) parametrique prete pour le calcul.

Lancement : freecadcmd make_cantilever_model.py   (ou depuis la console Python de FreeCAD)
Le modele est ecrit a cote du script : cantilever.FCStd

Geometrie : esquisse L x h dans le plan XY, extrudee de b selon Z.
  - encastrement sur la face x = 0
  - effort P (N) applique sur la face x = L, dirige selon -Y
Contraintes nommees de l'esquisse : L (longueur), h (hauteur). Extrusion : Pad.Length = b (largeur).
"""
import os
import FreeCAD as App
import Part
import Sketcher
import ObjectsFem

here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
out = os.path.join(here, "cantilever.FCStd")

L0, H0, B0, P0 = 100.0, 10.0, 10.0, 100.0

doc = App.newDocument("Cantilever")
body = doc.addObject("PartDesign::Body", "Body")
sk = body.newObject("Sketcher::SketchObject", "Sketch")
_sup = (doc.getObject("XY_Plane"), [""])
if hasattr(sk, "AttachmentSupport"):
    sk.AttachmentSupport = _sup   # FreeCAD >= 1.0
else:
    sk.Support = _sup             # FreeCAD 0.19-0.21
sk.MapMode = "FlatFace"
V = App.Vector
pts = [V(0, 0, 0), V(L0, 0, 0), V(L0, H0, 0), V(0, H0, 0)]
for i in range(4):
    sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
for i in range(4):
    sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
sk.addConstraint(Sketcher.Constraint("Vertical", 1))
sk.addConstraint(Sketcher.Constraint("Vertical", 3))
sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
i = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, L0)); sk.renameConstraint(i, "L")
i = sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, H0)); sk.renameConstraint(i, "h")
doc.recompute()
pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = sk
pad.Length = B0
doc.recompute()

shape = pad.Shape
def find_face(pred):
    for i, f in enumerate(shape.Faces, 1):
        if pred(f.CenterOfMass):
            return "Face%d" % i
fix_face = find_face(lambda c: abs(c.x) < 1e-6)
load_face = find_face(lambda c: abs(c.x - L0) < 1e-6)
y_edge = None
for i, e in enumerate(shape.Edges, 1):
    d = e.Vertexes[-1].Point - e.Vertexes[0].Point
    if abs(d.x) < 1e-9 and abs(d.z) < 1e-9 and abs(d.y) > 1:
        y_edge = "Edge%d" % i
        break

ana = ObjectsFem.makeAnalysis(doc, "Analysis")
_mk = getattr(ObjectsFem, "makeSolverCalculiXCcxTools", None) or getattr(ObjectsFem, "makeSolverCalculixCcxTools")
solver = _mk(doc, "SolverCcxTools")
solver.AnalysisType = "static"
solver.GeometricalNonlinearity = "linear"
solver.ThermoMechSteadyState = False
solver.MatrixSolverType = "default"
ana.addObject(solver)
mat = ObjectsFem.makeMaterialSolid(doc, "MaterialSolid")
m = mat.Material
m["Name"] = "Steel-Generic"
m["YoungsModulus"] = "210000 MPa"
m["PoissonRatio"] = "0.3"
m["Density"] = "7800 kg/m^3"
mat.Material = m
fix = ObjectsFem.makeConstraintFixed(doc, "ConstraintFixed")
fix.References = [(pad, fix_face)]
frc = ObjectsFem.makeConstraintForce(doc, "ConstraintForce")
frc.References = [(pad, load_face)]
frc.Force = "%g N" % P0
frc.Direction = (pad, [y_edge])
frc.Reversed = True   # effort selon -Y
mesh = ObjectsFem.makeMeshGmsh(doc, "FEMMeshGmsh")
mesh.Shape = pad
mesh.CharacteristicLengthMax = "3 mm"
mesh.ElementOrder = "2nd"
for o in (mat, fix, frc, mesh):
    ana.addObject(o)
doc.recompute()
doc.saveAs(out)
print("MODELE_ECRIT", out, "fix", fix_face, "load", load_face, "edge", y_edge, "volume", shape.Volume)
