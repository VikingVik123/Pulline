import os
import re
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import numpy as np
import ifcopenshell
import ifcopenshell.geom
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

# Optional imports with fallbacks
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
    Extracts ALL IFC elements, projects them to 2D footprints (XY),
    and exports CSV, DXF, SVG, PNG per storey.
    """
    
    def __init__(
        self,
        ifc_path: Path,
        output_dir: Path,
        z_tolerance: float = 0.05,
        min_segment_length: float = 0.05
    ):
        self.ifc_path = ifc_path
        self.output_dir = output_dir
        self.z_tolerance = z_tolerance
        self.min_segment_length = min_segment_length
        
        self.model = ifcopenshell.open(str(ifc_path))
        
        self.settings = ifcopenshell.geom.settings()
        self.settings.set(self.settings.USE_WORLD_COORDS, True)
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Store results
        self.segments_by_storey = {}
        self.storey_map = {}
    
    # ─────────────────────────────────────────────
    # STOREY MAP
    # ─────────────────────────────────────────────
    
    def get_storey_map(self) -> Dict[int, str]:
        """Map element IDs to storey names"""
        storey_map = {}
        
        for storey in self.model.by_type("IfcBuildingStorey"):
            name = getattr(storey, "Name", "Unknown")
            
            # Get elements contained in this storey
            for rel in (storey.ContainsElements or []):
                for elem in (rel.RelatedElements or []):
                    storey_map[elem.id()] = name
        
        # Also handle elements referenced through spatial structure
        for rel in self.model.by_type("IfcRelContainedInSpatialStructure"):
            relating_structure = rel.RelatingStructure
            if relating_structure.is_a("IfcBuildingStorey"):
                storey_name = getattr(relating_structure, "Name", "Unknown")
                for elem in rel.RelatedElements:
                    storey_map[elem.id()] = storey_name
        
        self.storey_map = storey_map
        return storey_map
    
    def filter_storeys(self, storeys: Optional[List[str]] = None) -> Optional[set]:
        """Convert storey filter to set"""
        if storeys:
            return set(storeys)
        return None
    
    def _safe_name(self, name: str) -> str:
        """Sanitize name for filename"""
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    
    def group_by_storey(self, segments: List[Dict]) -> Dict[str, List[Dict]]:
        """Group segments by storey"""
        grouped = defaultdict(list)
        for s in segments:
            grouped[s["storey"]].append(s)
        return dict(grouped)
    
    # ─────────────────────────────────────────────
    # ELEMENT COLLECTION
    # ─────────────────────────────────────────────
    
    def get_elements(self) -> List:
        """Get ALL spatial elements with geometry"""
        elements = []
        
        # Get all products that have representation
        for obj in self.model.by_type("IfcProduct"):
            if obj.Representation is not None:
                elements.append(obj)
        
        logger.info(f"Found {len(elements)} elements with geometry")
        return elements
    
    # ─────────────────────────────────────────────
    # GEOMETRY PROCESSING
    # ─────────────────────────────────────────────
    
    def extract_bottom_edges(self, verts: np.ndarray, faces: np.ndarray) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Extract bottom edges from 3D geometry"""
        if len(verts) == 0:
            return []
        
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
            p1 = (float(verts[a][0]), float(verts[a][1]))
            p2 = (float(verts[b][0]), float(verts[b][1]))
            
            length = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
            
            if length >= self.min_segment_length:
                segments.append((p1, p2))
        
        return segments
    
    # ─────────────────────────────────────────────
    # MAIN EXTRACTION
    # ─────────────────────────────────────────────
    
    def extract(self, storeys: Optional[List[str]] = None) -> List[Dict]:
        """Extract all segments from IFC file"""
        storey_filter = self.filter_storeys(storeys)
        self.get_storey_map()
        
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
                try:
                    shape = iterator.get()
                    elem = self.model.by_id(shape.id)
                    
                    verts = np.array(shape.geometry.verts).reshape(-1, 3)
                    faces = np.array(shape.geometry.faces).reshape(-1, 3)
                    
                    # Get storey name
                    storey = self.storey_map.get(shape.id, "Unknown")
                    
                    # Filter by storey
                    if storey_filter and storey not in storey_filter:
                        if not iterator.next():
                            break
                        continue
                    
                    # Extract bottom edges
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
                    
                    if count % 50 == 0:
                        logger.info(f"Processing elements: {count}/{len(elements)}")
                    
                    if not iterator.next():
                        break
                        
                except Exception as e:
                    logger.warning(f"Error processing element {count}: {e}")
                    if not iterator.next():
                        break
                    continue
        
        logger.info(f"Extracted {len(results)} segments from {count} elements")
        return results
    
    # ─────────────────────────────────────────────
    # EXPORT FUNCTIONS
    # ─────────────────────────────────────────────
    
    def export_csv(self, segments: List[Dict], filename: str) -> Path:
        """Export segments to CSV"""
        filepath = self.output_dir / filename
        
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["storey", "element", "x1", "y1", "x2", "y2", "length"])
            
            for s in segments:
                x1, y1 = s["p1"]
                x2, y2 = s["p2"]
                
                w.writerow([
                    s["storey"],
                    s["name"],
                    f"{x1:.6f}",
                    f"{y1:.6f}",
                    f"{x2:.6f}",
                    f"{y2:.6f}",
                    f"{np.hypot(x2 - x1, y2 - y1):.6f}"
                ])
        
        logger.info(f"CSV → {filepath}")
        return filepath
    
    def export_dxf(self, segments: List[Dict], filename: str) -> Optional[Path]:
        """Export segments to DXF"""
        if not HAS_EZDXF:
            logger.warning("DXF skipped (ezdxf missing)")
            return None
        
        filepath = self.output_dir / filename
        
        doc = ezdxf.new()
        msp = doc.modelspace()
        
        # Create layers for each storey
        storeys = {s["storey"] for s in segments}
        for st in storeys:
            doc.layers.add(name=st)
        
        for s in segments:
            x1, y1 = s["p1"]
            x2, y2 = s["p2"]
            
            msp.add_line(
                (x1, y1, 0),
                (x2, y2, 0),
                dxfattribs={"layer": s["storey"]}
            )
        
        doc.saveas(str(filepath))
        logger.info(f"DXF → {filepath}")
        return filepath
    
    def export_svg(self, segments: List[Dict], filename: str) -> Path:
        """Export segments to SVG"""
        filepath = self.output_dir / filename
        
        if not segments:
            return filepath
        
        xs = [c for s in segments for c in (s["p1"][0], s["p2"][0])]
        ys = [c for s in segments for c in (s["p1"][1], s["p2"][1])]
        
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        # Avoid division by zero
        range_x = max_x - min_x or 1
        range_y = max_y - min_y or 1
        
        scale = 800 / max(range_x, range_y)
        margin = 40
        
        def tx(x): return margin + (x - min_x) * scale
        def ty(y): return margin + (max_y - y) * scale
        
        svg_width = margin * 2 + range_x * scale
        svg_height = margin * 2 + range_y * scale
        
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{svg_width}" height="{svg_height}">',
            '<rect width="100%" height="100%" fill="white"/>'
        ]
        
        # Group by storey for color coding
        storeys = {s["storey"] for s in segments}
        colors = ['black', 'blue', 'red', 'green', 'orange', 'purple', 'brown']
        color_map = {st: colors[i % len(colors)] for i, st in enumerate(storeys)}
        
        for s in segments:
            x1, y1 = tx(s["p1"][0]), ty(s["p1"][1])
            x2, y2 = tx(s["p2"][0]), ty(s["p2"][1])
            
            color = color_map.get(s["storey"], 'black')
            
            svg.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{color}" stroke-width="1.5"/>'
            )
        
        svg.append("</svg>")
        
        with open(filepath, "w") as f:
            f.write("\n".join(svg))
        
        logger.info(f"SVG → {filepath}")
        return filepath
    
    def export_png(self, segments: List[Dict], filename: str) -> Optional[Path]:
        """Export segments to PNG"""
        if not HAS_MPL:
            logger.warning("PNG skipped (matplotlib missing)")
            return None
        
        filepath = self.output_dir / filename
        
        plt.figure(figsize=(12, 10))
        
        # Group by storey for color coding
        storeys = {s["storey"] for s in segments}
        colors = ['black', 'blue', 'red', 'green', 'orange', 'purple', 'brown']
        color_map = {st: colors[i % len(colors)] for i, st in enumerate(storeys)}
        
        for s in segments:
            x = [s["p1"][0], s["p2"][0]]
            y = [s["p1"][1], s["p2"][1]]
            plt.plot(x, y, color=color_map.get(s["storey"], 'black'), linewidth=0.8)
        
        plt.axis("equal")
        plt.axis("off")
        plt.tight_layout(pad=0)
        
        plt.savefig(filepath, dpi=300, bbox_inches="tight", pad_inches=0.1)
        plt.close()
        
        logger.info(f"PNG → {filepath}")
        return filepath
    
    def export_json(self, segments: List[Dict], filename: str) -> Path:
        """Export segments to JSON for laser projection"""
        import json
        
        filepath = self.output_dir / filename
        
        data = {
            "storey": segments[0]["storey"] if segments else "Unknown",
            "segments": [
                {
                    "element": s["name"],
                    "x1": s["p1"][0],
                    "y1": s["p1"][1],
                    "x2": s["p2"][0],
                    "y2": s["p2"][1],
                    "length": np.hypot(s["p2"][0] - s["p1"][0], s["p2"][1] - s["p1"][1])
                }
                for s in segments
            ]
        }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"JSON → {filepath}")
        return filepath
    
    # ─────────────────────────────────────────────
    # RUN PIPELINE
    # ─────────────────────────────────────────────
    
    def run(self, storeys: Optional[List[str]] = None) -> Dict[str, Dict[str, Path]]:
        """
        Run the full extraction pipeline.
        
        Returns:
            Dict mapping storey name to Dict of output file paths
        """
        segments = self.extract(storeys=storeys)
        
        # Group by storey
        grouped = self.group_by_storey(segments)
        
        output_files = {}
        
        for storey_name, segs in grouped.items():
            safe_name = self._safe_name(storey_name)
            
            logger.info(f"Exporting storey: {storey_name} ({len(segs)} segments)")
            
            # Create storey-specific subfolder
            storey_dir = self.output_dir / safe_name
            storey_dir.mkdir(parents=True, exist_ok=True)
            
            # Export all formats
            outputs = {
                "csv": self.export_csv(segs, storey_dir / f"{safe_name}.csv"),
                "svg": self.export_svg(segs, storey_dir / f"{safe_name}.svg"),
            }
            
            # Optional formats
            dxf_path = self.export_dxf(segs, storey_dir / f"{safe_name}.dxf")
            if dxf_path:
                outputs["dxf"] = dxf_path
            
            png_path = self.export_png(segs, storey_dir / f"{safe_name}.png")
            if png_path:
                outputs["png"] = png_path
            
            json_path = self.export_json(segs, storey_dir / f"{safe_name}.json")
            if json_path:
                outputs["json"] = json_path
            
            output_files[storey_name] = outputs
        
        return output_files