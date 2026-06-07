import ifcopenshell

model = ifcopenshell.open(r"C:\Users\HP\Documents\Hillside_House.ifc")

#print(model.schema)
#print(model.by_id(1))

"""
for entity in model.by_type("IfcBuilding"):
    print(entity)
"""

"""
walls = model.by_type("IfcWall")
print("Walls:", len(walls))
"""
"""
if walls:
    import ifcopenshell.geom
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    shape = ifcopenshell.geom.create_shape(settings, walls[0])
    print(len(shape.geometry.verts))
"""

for storey in model.by_type("IfcBuildingStorey"):
    print(storey.Name)

for storey in model.by_type("IfcBuildingStorey"):
    print(
        storey.Name,
        getattr(storey, "Elevation", None)
    )

#for storey in model.by_type("IfcBuildingStorey"):
#    print(f"\n{storey.Name}")

"""
    if hasattr(storey, "ContainsElements"):
        for rel in storey.ContainsElements:
            for elem in rel.RelatedElements:
                print(" ", elem.is_a(), elem.GlobalId)
"""

print(len(model.by_type("IfcWall")))
print(len(model.by_type("IfcSlab")))
print(len(model.by_type("IfcSpace")))

foundation_walls = []

for wall in model.by_type("IfcWall"):
    for rel in wall.ContainedInStructure:
        storey = rel.RelatingStructure

        if storey.Name == "Foundation":
            foundation_walls.append(wall)
            print(wall.GlobalId)

print("Foundation walls:", len(foundation_walls))