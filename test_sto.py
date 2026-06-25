import ifcopenshell
import ifcopenshell.geom
import numpy as np
import csv
import os
import re

from sqlalchemy.util import defaultdict

try:
    import ezdxf
    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False

try:
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


class IFCElementExtractor:
    """
    Extracts ALL IFC elements (not just walls),
    projects them to 2D footprints (XY),
    and exports SVG, DXF, PNG, CSV.
    """

    def __init__(
        self,
        ifc_path: str,
        output_dir: str,
        z_tolerance: float = 0.05,
        min_segment_length: float = 0.05
    ):
        self.ifc_path = ifc_path
        self.output_dir = output_dir
        self.z_tolerance = z_tolerance
        self.min_segment_length = min_segment_length

        self.model = ifcopenshell.open(ifc_path)

        self.settings = ifcopenshell.geom.settings()
        self.settings.set(self.settings.USE_WORLD_COORDS, True)

        os.makedirs(self.output_dir, exist_ok=True)

    # ─────────────────────────────────────────────
    # STOREY MAP
    # ─────────────────────────────────────────────

    def get_storey_map(self):
        storey_map = {}

        for storey in self.model.by_type("IfcBuildingStorey"):
            name = getattr(storey, "Name", "Unknown")

            for rel in (storey.ContainsElements or []):
                for elem in (rel.RelatedElements or []):
                    storey_map[elem.id()] = name

        return storey_map

    def filter_storeys(self, storeys):
        return set(storeys) if storeys else None
    

    def _safe_name(self, name: str):
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    
    def group_by_storey(self, segments):
        grouped = defaultdict(list)

        for s in segments:
            grouped[s["storey"]].append(s)

        return grouped

    # ─────────────────────────────────────────────
    # ELEMENT COLLECTION (ALL)
    # ─────────────────────────────────────────────

    def get_elements(self):
        """
        Get ALL spatial elements with geometry.
        (walls, slabs, beams, columns, etc.)
        """
        elements = []
        for obj in self.model.by_type("IfcProduct"):
            if obj.Representation is not None:
                elements.append(obj)

        return elements

    # ─────────────────────────────────────────────
    # GEOMETRY PROCESSING
    # ─────────────────────────────────────────────

    def extract_bottom_edges(self, verts, faces):
        z_min = verts[:, 2].min()
        threshold = z_min + self.z_tolerance

        bottom_idx = set(np.where(verts[:, 2] <= threshold)[0])

        edges = set()

        for face in faces:
            for i in range(3):
                a, b = face[i], face[(i + 1) % 3]
                if a in bottom_idx and b in bottom_idx:
                    edges.add((min(a, b), max(a, b)))

        segments = []

        for a, b in edges:
            p1 = (verts[a][0], verts[a][1])
            p2 = (verts[b][0], verts[b][1])

            length = np.hypot(p2[0] - p1[0], p2[1] - p1[1])

            if length >= self.min_segment_length:
                segments.append((p1, p2))

        return segments

    # ─────────────────────────────────────────────
    # MAIN EXTRACTION
    # ─────────────────────────────────────────────

    def extract(self, storeys=None):
        storey_filter = self.filter_storeys(storeys)
        storey_map = self.get_storey_map()

        elements = self.get_elements()

        iterator = ifcopenshell.geom.iterator(
            self.settings,
            self.model,
            include=elements
        )

        results = []
        count = 0

        if iterator.initialize():
            while True:
                shape = iterator.get()
                elem = self.model.by_id(shape.id)

                verts = np.array(shape.geometry.verts).reshape(-1, 3)
                faces = np.array(shape.geometry.faces).reshape(-1, 3)

                storey = storey_map.get(shape.id, "Unknown")

                # storey filter
                if storey_filter and storey not in storey_filter:
                    if not iterator.next():
                        break
                    continue

                segs = self.extract_bottom_edges(verts, faces)

                name = getattr(elem, "Name", f"ID_{shape.id}")

                for p1, p2 in segs:
                    results.append({
                        "name": name,
                        "storey": storey,
                        "p1": p1,
                        "p2": p2
                    })

                count += 1
                print(f"\rProcessing elements: {count}/{len(elements)}", end="")

                if not iterator.next():
                    break

        print(f"\nExtracted {len(results)} segments")
        return results

    # ─────────────────────────────────────────────
    # EXPORT CSV
    # ─────────────────────────────────────────────

    def export_csv(self, segments, name="output.csv"):
        path = os.path.join(self.output_dir, name)

        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["storey", "element", "x1", "y1", "x2", "y2", "length"])

            for s in segments:
                x1, y1 = s["p1"]
                x2, y2 = s["p2"]

                w.writerow([
                    s["storey"],
                    s["name"],
                    x1, y1, x2, y2,
                    np.hypot(x2 - x1, y2 - y1)
                ])

        print(f"CSV → {path}")

    # ─────────────────────────────────────────────
    # EXPORT DXF
    # ─────────────────────────────────────────────

    def export_dxf(self, segments, name="output.dxf"):
        if not HAS_EZDXF:
            print("DXF skipped (ezdxf missing)")
            return

        path = os.path.join(self.output_dir, name)

        doc = ezdxf.new()
        msp = doc.modelspace()

        storeys = {s["storey"] for s in segments}
        for st in storeys:
            doc.layers.add(name=st)

        for s in segments:
            x1, y1 = s["p1"]
            x2, y2 = s["p2"]

            msp.add_line((x1, y1, 0), (x2, y2, 0),
                         dxfattribs={"layer": s["storey"]})

        doc.saveas(path)
        print(f"DXF → {path}")

    # ─────────────────────────────────────────────
    # EXPORT SVG
    # ─────────────────────────────────────────────

    def export_svg(self, segments, name="output.svg"):
        if not segments:
            return

        path = os.path.join(self.output_dir, name)

        xs = [c for s in segments for c in (s["p1"][0], s["p2"][0])]
        ys = [c for s in segments for c in (s["p1"][1], s["p2"][1])]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        scale = 800 / max(max_x - min_x, max_y - min_y)

        def tx(x): return (x - min_x) * scale
        def ty(y): return (max_y - y) * scale

        svg = ['<svg xmlns="http://www.w3.org/2000/svg">']

        for s in segments:
            x1, y1 = tx(s["p1"][0]), ty(s["p1"][1])
            x2, y2 = tx(s["p2"][0]), ty(s["p2"][1])

            svg.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="black" stroke-width="1"/>'
            )

        svg.append("</svg>")

        with open(path, "w") as f:
            f.write("\n".join(svg))

        print(f"SVG → {path}")

    # ─────────────────────────────────────────────
    # EXPORT PNG (NEW)
    # ─────────────────────────────────────────────

    def export_png(self, segments, name="output.png"):
        if not HAS_MPL:
            print("PNG skipped (matplotlib missing)")
            return

        path = os.path.join(self.output_dir, name)

        plt.figure()

        for s in segments:
            x = [s["p1"][0], s["p2"][0]]
            y = [s["p1"][1], s["p2"][1]]
            plt.plot(x, y, "k-", linewidth=0.5)

        plt.axis("equal")
        plt.axis("off")

        plt.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0)
        plt.close()

        print(f"PNG → {path}")

    # ─────────────────────────────────────────────
    # RUN PIPELINE
    # ─────────────────────────────────────────────

    def run(self, storeys=None):
        segments = self.extract(storeys=storeys)

        grouped = self.group_by_storey(segments)

        for storey_name, segs in grouped.items():

            safe = self._safe_name(storey_name)

            print(f"\nExporting storey: {storey_name} ({len(segs)} segments)")

            self.export_csv(segs, name=f"{safe}.csv")
            self.export_dxf(segs, name=f"{safe}.dxf")
            self.export_svg(segs, name=f"{safe}.svg")
            self.export_png(segs, name=f"{safe}.png")

        return segments
    


IFC_PATH   = r"C:\Users\HP\Documents\Mr. Okafor Sunday.ifc"
OUTPUT_DIR = r"C:\Users\HP\Documents\Pulline\output"


ex = IFCElementExtractor(IFC_PATH, OUTPUT_DIR)
ex.run(storeys=["Ground Floor"])