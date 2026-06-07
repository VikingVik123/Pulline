"""
extract_walls.py
----------------
Extracts wall footprints (bottom face edges) from an IFC file.
Outputs:
  - walls.dxf   → for drone/laser projection systems
  - walls.csv   → fallback, list of line segments (X1,Y1,X2,Y2)
  - walls.svg   → quick visual check before loading into hardware

Usage:
    python extract_walls.py

Requirements:
    pip install ifcopenshell numpy ezdxf
"""

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import csv
import os

try:
    import ezdxf
    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False
    print("  [!] ezdxf not installed — DXF output will be skipped.")
    print("      Run: pip install ezdxf")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

IFC_PATH   = r"C:\Users\Victor\Documents\Hillside_House.ifc"
OUTPUT_DIR = r"C:\Users\Victor\Documents\Pulline\output"

# Only extract these types (all wall variants)
WALL_TYPES = {"IfcWall", "IfcWallStandardCase"}

# Z tolerance — edges within this distance of the element's
# lowest Z are considered the "bottom face" (floor-level footprint)
Z_TOLERANCE = 0.05   # metres

# Minimum segment length to keep (filters noise/tiny edges)
MIN_SEGMENT_LENGTH = 0.05   # metres

# ─────────────────────────────────────────────
# GEOMETRY HELPERS
# ─────────────────────────────────────────────

def get_wall_elements(model):
    """Return all wall elements that have geometry."""
    walls = []
    for wtype in WALL_TYPES:
        for elem in model.by_type(wtype):
            if elem.Representation is not None:
                walls.append(elem)
    print(f"  Found {len(walls)} wall elements with geometry.")
    return walls


def extract_bottom_edges(verts, faces, z_tolerance=Z_TOLERANCE):
    """
    Given a triangle mesh, extract the edges that lie on the
    bottom face (lowest Z plane) of the element.

    Returns list of (p1, p2) pairs — each a 2D (x, y) tuple.
    """
    z_min = verts[:, 2].min()
    z_threshold = z_min + z_tolerance

    # Find vertices on the bottom face
    bottom_mask = verts[:, 2] <= z_threshold
    bottom_idx  = set(np.where(bottom_mask)[0])

    edges = set()
    for face in faces:
        for i in range(3):
            a = face[i]
            b = face[(i + 1) % 3]
            if a in bottom_idx and b in bottom_idx:
                # Normalise edge direction so (a,b) == (b,a)
                edge = (min(a, b), max(a, b))
                edges.add(edge)

    segments = []
    for a, b in edges:
        p1 = (float(verts[a][0]), float(verts[a][1]))
        p2 = (float(verts[b][0]), float(verts[b][1]))

        # Filter tiny segments
        length = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if length >= MIN_SEGMENT_LENGTH:
            segments.append((p1, p2))

    return segments


def get_all_wall_segments(model):
    """
    Batch-process all walls, return list of segment dicts:
    { name, storey, p1:(x,y), p2:(x,y) }
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    walls    = get_wall_elements(model)
    wall_ids = {w.id(): w for w in walls}

    # Build storey lookup: element_id → storey name
    storey_map = {}
    for storey in model.by_type("IfcBuildingStorey"):
        for rel in (storey.ContainsElements or []):
            for elem in (rel.RelatedElements or []):
                storey_map[elem.id()] = getattr(storey, "Name", "Unknown")

    # Use iterator — much faster than per-element
    include    = list(wall_ids.values())
    iterator   = ifcopenshell.geom.iterator(settings, model, include=include)

    all_segments = []
    count        = 0

    if iterator.initialize():
        while True:
            shape  = iterator.get()
            elem   = model.by_id(shape.id)
            verts  = np.array(shape.geometry.verts).reshape(-1, 3)
            faces  = np.array(shape.geometry.faces).reshape(-1, 3)

            segs = extract_bottom_edges(verts, faces)

            name   = getattr(elem, "Name", f"ID_{shape.id}")
            storey = storey_map.get(shape.id, "Unknown")

            for p1, p2 in segs:
                all_segments.append({
                    "name":   name,
                    "storey": storey,
                    "p1":     p1,
                    "p2":     p2,
                })

            count += 1
            print(f"\r  Processing walls... {count}/{len(walls)}", end="", flush=True)

            if not iterator.next():
                break

    print(f"\n  Extracted {len(all_segments)} line segments from {count} walls.")
    return all_segments


# ─────────────────────────────────────────────
# EXPORTS
# ─────────────────────────────────────────────

def export_csv(segments, path):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["storey", "wall_name", "x1", "y1", "x2", "y2", "length_m"])
        for s in segments:
            x1, y1 = s["p1"]
            x2, y2 = s["p2"]
            length  = round(np.hypot(x2 - x1, y2 - y1), 4)
            writer.writerow([
                s["storey"], s["name"],
                round(x1, 4), round(y1, 4),
                round(x2, 4), round(y2, 4),
                length
            ])
    print(f"  CSV saved  → {path}")


def export_dxf(segments, path):
    if not HAS_EZDXF:
        print("  DXF skipped — install ezdxf.")
        return

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()

    # One layer per storey
    storeys = {s["storey"] for s in segments}
    for storey in storeys:
        doc.layers.add(name=storey)

    for s in segments:
        x1, y1 = s["p1"]
        x2, y2 = s["p2"]
        msp.add_line(
            (x1, y1, 0),
            (x2, y2, 0),
            dxfattribs={"layer": s["storey"]}
        )

    doc.saveas(path)
    print(f"  DXF saved  → {path}")


def export_svg(segments, path):
    """Lightweight SVG for visual sanity check — no dependencies."""
    if not segments:
        return

    all_x = [c for s in segments for c in (s["p1"][0], s["p2"][0])]
    all_y = [c for s in segments for c in (s["p1"][1], s["p2"][1])]

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    w = max_x - min_x
    h = max_y - min_y
    pad   = 2.0
    scale = 800 / max(w, h)     # fit in 800px

    def tx(x): return (x - min_x + pad) * scale
    def ty(y): return (max_y - y + pad) * scale  # flip Y for SVG

    svg_w = int((w + pad * 2) * scale)
    svg_h = int((h + pad * 2) * scale)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'style="background:#f8f8f8">',
    ]

    # Colour per storey
    palette = ["#2c3e50","#e74c3c","#2980b9","#27ae60","#8e44ad","#f39c12"]
    storey_list = sorted({s["storey"] for s in segments})
    storey_color = {st: palette[i % len(palette)] for i, st in enumerate(storey_list)}

    for s in segments:
        x1, y1 = tx(s["p1"][0]), ty(s["p1"][1])
        x2, y2 = tx(s["p2"][0]), ty(s["p2"][1])
        color   = storey_color[s["storey"]]
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="1" />'
        )

    # Legend
    for i, (st, col) in enumerate(storey_color.items()):
        lines.append(
            f'<rect x="10" y="{10 + i*20}" width="12" height="12" fill="{col}"/>'
            f'<text x="28" y="{21 + i*20}" font-size="12" fill="#333">{st}</text>'
        )

    lines.append("</svg>")

    with open(path, "w") as f:
        f.write("\n".join(lines))

    print(f"  SVG saved  → {path}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\nLoading: {IFC_PATH}")
    model = ifcopenshell.open(IFC_PATH)

    print("\nExtracting wall footprints...")
    segments = get_all_wall_segments(model)

    print("\nExporting...")
    export_csv(segments, os.path.join(OUTPUT_DIR, "walls.csv"))
    export_dxf(segments, os.path.join(OUTPUT_DIR, "walls.dxf"))
    export_svg(segments, os.path.join(OUTPUT_DIR, "walls.svg"))

    print(f"\nDone. Files in: {OUTPUT_DIR}")
    print("  walls.dxf  → load into drone/projection hardware")
    print("  walls.csv  → fallback, raw line segments")
    print("  walls.svg  → open in browser to sanity-check the outline")