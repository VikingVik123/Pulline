import ifcopenshell.geom
import numpy as np

from test import model, model2

settings = ifcopenshell.geom.settings()
settings.set(settings.USE_WORLD_COORDS, True)

def get_element_geometry(element, settings):
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
        geo = shape.geometry

        # Raw triangle mesh
        verts = np.array(geo.verts).reshape(-1, 3)   # (N, 3) XYZ points
        faces = np.array(geo.faces).reshape(-1, 3)   # triangle indices

        # Bounding box (min/max corners)
        bbox_min = verts.min(axis=0)
        bbox_max = verts.max(axis=0)
        centroid = verts.mean(axis=0)

        return {
            "vertices": verts,
            "faces": faces,
            "bbox_min": bbox_min,   # [x, y, z]
            "bbox_max": bbox_max,
            "centroid": centroid,
        }
    except Exception as e:
        return None
    
def get_all_geometry(model):

    iterator = ifcopenshell.geom.iterator(settings, model)
    geometry_map = {}

    if iterator.initialize():
        while True:
            shape = iterator.get()
            elem = model.by_id(shape.id)

            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            geometry_map[shape.id] = {
                "type": elem.is_a(),
                "name": getattr(elem, "Name", None),
                "centroid": verts.mean(axis=0),
                "bbox_min": verts.min(axis=0),
                "bbox_max": verts.max(axis=0),
            }

            if not iterator.next():
                break

    return geometry_map


if __name__ == "__main__":
    geo_map = get_all_geometry(model)
    
    for elem_id, data in geo_map.items():
        print(f"ID={elem_id:<8} TYPE={data['type']:<30} NAME={data['name']:<20} CENTROID={data['centroid'].round(3)}")