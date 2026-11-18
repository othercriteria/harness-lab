from .catalog_loader import load_catalog

def plan(features, target):
    catalog = load_catalog()
    return [target]
