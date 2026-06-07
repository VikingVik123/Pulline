import ifcopenshell
from collections import defaultdict



model = ifcopenshell.open(
    r"C:\Users\Victor\Documents\Hillside_House.ifc"
)

model2 = ifcopenshell.open(
    r"C:\Users\Victor\Documents\Mr. Okafor Sunday.ifc"
)

# -----------------------------
# SAFE HELPERS
# -----------------------------

def safe_get(attr, default=[]):
    if attr is None:
        return []
    return attr


def get_sites(model):
    return model.by_type("IfcSite")


def get_buildings(site):
    """
    Site → Building relationships
    """
    buildings = []

    for rel in safe_get(site.IsDecomposedBy):
        for obj in safe_get(rel.RelatedObjects):
            if obj.is_a("IfcBuilding"):
                buildings.append(obj)

    return buildings


def get_storeys(building):
    """
    Building → Storeys
    """
    storeys = []

    for rel in safe_get(building.IsDecomposedBy):
        for obj in safe_get(rel.RelatedObjects):
            if obj.is_a("IfcBuildingStorey"):
                storeys.append(obj)

    return storeys


def get_spaces(storey):
    """
    Storey → Spaces
    """
    spaces = []

    for rel in safe_get(storey.ContainsElements):
        for obj in safe_get(rel.RelatedElements):
            if obj.is_a("IfcSpace"):
                spaces.append(obj)

    return spaces


def get_storey_elements(storey):
    """
    Storey → Elements (non-space)
    """
    elements = []

    for rel in safe_get(storey.ContainsElements):
        for obj in safe_get(rel.RelatedElements):
            if not obj.is_a("IfcSpace"):
                elements.append(obj)

    return elements


def group_by_type(elements):
    """
    Group elements by IFC type
    """
    inventory = defaultdict(list)

    for e in elements:
        inventory[e.is_a()].append(e)

    return inventory


# -----------------------------
# TREE WALKER
# -----------------------------

def walk_ifc_tree(model):

    for site in get_sites(model):

        print("\n" + "#" * 80)
        print(f"SITE: {getattr(site, 'Name', 'Unnamed Site')}")
        print("#" * 80)

        for building in get_buildings(site):

            print("\n" + "=" * 80)
            print(f"BUILDING: {getattr(building, 'Name', 'Unnamed Building')}")
            print("=" * 80)

            for storey in get_storeys(building):

                print("\n" + "-" * 80)
                print(f"STOREY: {getattr(storey, 'Name', 'Unnamed Storey')}")
                print("-" * 80)

                # SPACES
                spaces = get_spaces(storey)
                print(f"\nSPACES ({len(spaces)})")
                for s in spaces:
                    print(f"ID={s.id():<8} NAME={getattr(s, 'Name', None)}")

                # ELEMENTS
                elements = get_storey_elements(storey)
                inventory = group_by_type(elements)

                total = 0

                for ifc_type, items in inventory.items():
                    total += len(items)

                    print(f"\n{ifc_type} ({len(items)})")
                    print("-" * 50)

                    for e in items[:10]:
                        print(f"ID={e.id():<8} NAME={getattr(e, 'Name', None)}")

                    if len(items) > 10:
                        print(f"... +{len(items)-10} more")

                print(f"\nTOTAL ELEMENTS IN STOREY: {total}")


# -----------------------------
# ENTRY POINT
# -----------------------------

if __name__ == "__main__":
    walk_ifc_tree(model)