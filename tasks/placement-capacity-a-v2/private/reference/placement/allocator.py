from .loader import load


def _can_place(services, eligible, remaining):
    """Test feasibility with augmenting paths over individual worker slots."""
    slots = [worker for worker in sorted(remaining)
             for _ in range(remaining[worker])]
    owner = [None] * len(slots)

    def augment(service, visited):
        for slot, worker in enumerate(slots):
            if slot in visited or worker not in eligible[service]:
                continue
            visited.add(slot)
            if owner[slot] is None or augment(owner[slot], visited):
                owner[slot] = service
                return True
        return False

    return all(augment(service, set()) for service in services)


def allocate(service_ids, profile):
    workers, compute, storage = load()
    enabled = set(workers["profiles"][profile]["enabled_workers"])
    services = sorted(service_ids)
    eligible = {
        service: (set(compute[service]["compute_workers"])
                  & set(storage[service]["storage_workers"]) & enabled)
        for service in services
    }
    remaining = {worker: workers["workers"][worker]["slots"]
                 for worker in enabled}
    result = {}
    for index, service in enumerate(services):
        for worker in sorted(eligible[service]):
            if not remaining[worker]:
                continue
            remaining[worker] -= 1
            if _can_place(services[index + 1:], eligible, remaining):
                result[service] = worker
                break
            remaining[worker] += 1
        else:
            # Unreachable for the supplied profiles and supported service sets.
            raise ValueError("No complete allocation exists")
    return result
