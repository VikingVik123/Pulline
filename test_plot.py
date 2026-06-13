"""
plot_ifc.py
-----------
Reads an IFC file, extracts element centroids + bounding boxes,
and saves a 2D floor plan PNG per storey (top-down XY view).
Also saves a CSV of all coordinates.

Usage:
    python plot_ifc.py
"""

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import matplotlib
matplotlib.use("Agg")                     # no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.lines import Line2D
import csv
import os
from collections import defaultdict

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

IFC_PATH   = r"C:\Users\HP\Documents\Hillside_House.ifc"
OUTPUT_DIR = r"C:\Users\HP\Documents\Pulline\output"
TARGET_STOREY = "Ground Floor"
# Colour per IFC type (top-down view)
TYPE_STYLE = {
    "IfcWall":                 dict(color="#2c3e50", alpha=0.9, zorder=4),
    "IfcWallStandardCase":     dict(color="#2c3e50", alpha=0.9, zorder=4),
    "IfcColumn":               dict(color="#8e44ad", alpha=1.0, zorder=5),
    "IfcBeam":                 dict(color="#2980b9", alpha=0.6, zorder=3),
    "IfcSlab":                 dict(color="#bdc3c7", alpha=0.3, zorder=1),
    "IfcDoor":                 dict(color="#e67e22", alpha=0.9, zorder=6),
    "IfcWindow":               dict(color="#3498db", alpha=0.8, zorder=6),
    "IfcStair":                dict(color="#27ae60", alpha=0.7, zorder=4),
    "IfcFooting":              dict(color="#795548", alpha=0.7, zorder=3),
    "IfcRailing":              dict(color="#f39c12", alpha=0.8, zorder=5),
    "IfcFurnishingElement":    dict(color="#1abc9c", alpha=0.5, zorder=2),
    "IfcBuildingElementProxy": dict(color="#95a5a6", alpha=0.3, zorder=1),
    "IfcCovering":             dict(color="#d5dbdb", alpha=0.2, zorder=1),
    "IfcDiscreteAccessory":    dict(color="#e74c3c", alpha=0.6, zorder=4),
    "IfcFlowTerminal":         dict(color="#f1c40f", alpha=0.6, zorder=3),
    "IfcFlowSegment":          dict(color="#f1c40f", alpha=0.4, zorder=2),
}
DEFAULT_STYLE = dict(color="#aaaaaa", alpha=0.4, zorder=1)

# ─────────────────────────────────────────────
# HELPERS — spatial tree
# ─────────────────────────────────────────────

def safe_get(attr):
    return attr if attr is not None else []

def get_sites(model):
    return model.by_type("IfcSite")

def get_buildings(site):
    return [obj for rel in safe_get(site.IsDecomposedBy)
            for obj in safe_get(rel.RelatedObjects)
            if obj.is_a("IfcBuilding")]

def get_storeys(building):
    storeys = [obj for rel in safe_get(building.IsDecomposedBy)
               for obj in safe_get(rel.RelatedObjects)
               if obj.is_a("IfcBuildingStorey")]
    storeys.sort(key=lambda s: getattr(s, "Elevation", 0) or 0)
    return storeys

def get_storey_elements(storey):
    elements = []
    for rel in safe_get(storey.ContainsElements):
        for obj in safe_get(rel.RelatedElements):
            if not obj.is_a("IfcSpace"):
                elements.append(obj)
    return elements

# ─────────────────────────────────────────────
# GEOMETRY EXTRACTION
# ─────────────────────────────────────────────

def build_geometry_map(model):
    """Batch-extract all geometry. Returns {element_id: geo_dict}."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    iterator = ifcopenshell.geom.iterator(settings, model)
    geo_map  = {}
    count    = 0

    if iterator.initialize():
        while True:
            shape = iterator.get()
            elem  = model.by_id(shape.id)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)

            geo_map[shape.id] = {
                "type":     elem.is_a(),
                "name":     getattr(elem, "Name", None),
                "centroid": verts.mean(axis=0),
                "bbox_min": verts.min(axis=0),
                "bbox_max": verts.max(axis=0),
                "verts":    verts,
            }

            count += 1
            print(f"\r  Extracting geometry... {count} elements", end="", flush=True)

            if not iterator.next():
                break

    print(f"\n  Done — {count} elements processed.")
    return geo_map

# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────

def export_csv(model, geo_map, path):
    rows = []

    for site in get_sites(model):
        site_name = getattr(site, "Name", "Site")
        for building in get_buildings(site):
            bld_name = getattr(building, "Name", "Building")
            for storey in get_storeys(building):
                sty_name = getattr(storey, "Name", "Storey")
                for elem in get_storey_elements(storey):
                    geo = geo_map.get(elem.id())
                    if geo is None:
                        continue
                    c    = geo["centroid"]
                    bmin = geo["bbox_min"]
                    bmax = geo["bbox_max"]
                    size = bmax - bmin
                    rows.append({
                        "site":       site_name,
                        "building":   bld_name,
                        "storey":     sty_name,
                        "id":         elem.id(),
                        "ifc_type":   elem.is_a(),
                        "name":       getattr(elem, "Name", ""),
                        "cx":         round(float(c[0]),  4),
                        "cy":         round(float(c[1]),  4),
                        "cz":         round(float(c[2]),  4),
                        "size_x":     round(float(size[0]), 4),
                        "size_y":     round(float(size[1]), 4),
                        "size_z":     round(float(size[2]), 4),
                        "bbox_min_x": round(float(bmin[0]), 4),
                        "bbox_min_y": round(float(bmin[1]), 4),
                        "bbox_min_z": round(float(bmin[2]), 4),
                        "bbox_max_x": round(float(bmax[0]), 4),
                        "bbox_max_y": round(float(bmax[1]), 4),
                        "bbox_max_z": round(float(bmax[2]), 4),
                    })

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV saved → {path}  ({len(rows)} rows)")

# ─────────────────────────────────────────────
# 2D PLOT — one PNG per storey
# ─────────────────────────────────────────────

def plot_storey(storey_name, elements_geo, out_path):
    """
    elements_geo: list of geo dicts (with ifc_type, name, bbox_min/max, centroid)
    Top-down XY view. Each element drawn as its bbox footprint rectangle.
    """
    if not elements_geo:
        print(f"  Skipping {storey_name} — no geometry")
        return

    fig, ax = plt.subplots(figsize=(16, 16))
    ax.set_aspect("equal")
    ax.set_facecolor("#f8f9fa")
    fig.patch.set_facecolor("#ffffff")

    # Group for legend
    seen_types = set()

    for geo in elements_geo:
        ifc_type = geo["type"]
        bmin     = geo["bbox_min"]
        bmax     = geo["bbox_max"]
        style    = TYPE_STYLE.get(ifc_type, DEFAULT_STYLE)

        # XY footprint rectangle
        x      = float(bmin[0])
        y      = float(bmin[1])
        width  = float(bmax[0] - bmin[0])
        height = float(bmax[1] - bmin[1])

        # Skip degenerate (zero-area) footprints
        if width < 0.001 and height < 0.001:
            # Draw as point instead
            cx, cy = float(geo["centroid"][0]), float(geo["centroid"][1])
            ax.plot(cx, cy, "o", color=style["color"],
                    markersize=3, alpha=style["alpha"], zorder=style["zorder"])
        else:
            rect = patches.Rectangle(
                (x, y), width, height,
                linewidth=0.5,
                edgecolor=style["color"],
                facecolor=style["color"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )
            ax.add_patch(rect)

        seen_types.add(ifc_type)

    # Legend
    legend_handles = [
        Line2D([0], [0],
               marker="s", color="w",
               markerfacecolor=TYPE_STYLE.get(t, DEFAULT_STYLE)["color"],
               markersize=10, label=t.replace("Ifc", ""))
        for t in sorted(seen_types)
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              fontsize=7, framealpha=0.9)

    # Auto-fit view
    all_x = [float(g["centroid"][0]) for g in elements_geo]
    all_y = [float(g["centroid"][1]) for g in elements_geo]
    pad   = 2.0
    ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
    ax.set_ylim(min(all_y) - pad, max(all_y) + pad)

    ax.set_title(f"Floor Plan — {storey_name}", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.5)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  PNG saved → {out_path}")


def export_plots(model, geo_map, out_dir):
    for site in get_sites(model):
        for building in get_buildings(site):

            bld_name = getattr(building, "Name", "Building")

            for storey in get_storeys(building):

                sty_name = getattr(storey, "Name", "Storey")

                # Skip other floors if a target is specified
                if TARGET_STOREY is not None:
                    if sty_name.lower() != TARGET_STOREY.lower():
                        continue

                elements = get_storey_elements(storey)

                elements_geo = []

                for elem in elements:
                    geo = geo_map.get(elem.id())

                    if geo:
                        elements_geo.append(geo)

                safe_name = sty_name.replace(" ", "_").replace("/", "-")

                out_path = os.path.join(
                    out_dir,
                    f"{bld_name}_{safe_name}.png"
                )

                print(
                    f"\nPlotting: {bld_name} / {sty_name} "
                    f"({len(elements_geo)} elements)"
                )

                plot_storey(
                    sty_name,
                    elements_geo,
                    out_path
                )

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\nLoading: {IFC_PATH}")
    model = ifcopenshell.open(IFC_PATH)

    print("\nExtracting geometry...")
    geo_map = build_geometry_map(model)

    print("\nExporting CSV...")
    export_csv(model, geo_map, os.path.join(OUTPUT_DIR, "coordinates.csv"))

    print("\nGenerating floor plan PNGs...")
    export_plots(model, geo_map, OUTPUT_DIR)

    print(f"\nAll done. Check: {OUTPUT_DIR}")