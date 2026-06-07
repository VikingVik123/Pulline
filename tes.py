import sys
import ezdxf

try:
    doc = ezdxf.readfile(r"C:\Users\HP\Documents\Hillside House.dxf")
except IOError:
    print(f"Not a DXF file or a generic I/O error.")
    sys.exit(1)
except ezdxf.DXFStructureError:
    print(f"Invalid or corrupted DXF file.")
    sys.exit(2)

msp = doc.modelspace()

entity_counts = {}

for e in msp:
    entity_counts[e.dxftype()] = entity_counts.get(
        e.dxftype(), 0
    ) + 1

print(entity_counts)

walls = []

for poly in msp.query("LWPOLYLINE"):
    points = [(p[0], p[1]) for p in poly.get_points()]
    walls.append(points)

print(walls[:2])