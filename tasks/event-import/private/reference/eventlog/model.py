def normalize_event(event):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    for field in ("id", "kind"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    if type(event.get("value")) is not int:
        raise ValueError("value must be an integer")
    return {
        "id": event["id"].strip(),
        "kind": event["kind"].strip().lower(),
        "value": event["value"],
    }
