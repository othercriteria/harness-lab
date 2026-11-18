import heapq

from .catalog_loader import load_catalog


def plan(features, target):
    catalog = load_catalog()
    dependencies = {
        plugin: {
            rule["plugin"]
            for rule in rules
            if all(feature in features for feature in rule["when"])
        }
        for plugin, rules in catalog.items()
    }

    selected = set()
    pending = [target]
    while pending:
        plugin = pending.pop()
        if plugin not in selected:
            selected.add(plugin)
            pending.extend(dependencies[plugin])

    remaining = {plugin: len(dependencies[plugin]) for plugin in selected}
    dependents = {plugin: set() for plugin in selected}
    for plugin in selected:
        for dependency in dependencies[plugin]:
            dependents[dependency].add(plugin)

    runnable = [plugin for plugin in selected if remaining[plugin] == 0]
    heapq.heapify(runnable)
    result = []
    while runnable:
        plugin = heapq.heappop(runnable)
        result.append(plugin)
        for dependent in dependents[plugin]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                heapq.heappush(runnable, dependent)
    return result
