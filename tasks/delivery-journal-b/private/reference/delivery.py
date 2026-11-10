from interfaces import DeliveryUncertain


def advance(job, store, remote):
    job_id = job["id"]
    payload = job["payload"]
    record = store.load(job_id)

    if record is not None:
        if record["payload"] != payload:
            raise ValueError("job ID already belongs to a different payload")
        if record["done"]:
            return "done"
    else:
        store.save(job_id, {"payload": payload, "done": False})

    try:
        remote.apply(job_id, payload)
    except DeliveryUncertain:
        return "retry"

    store.save(job_id, {"payload": payload, "done": True})
    return "done"
