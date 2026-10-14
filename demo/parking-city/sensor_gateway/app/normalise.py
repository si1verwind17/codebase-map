import itertools

_seq = itertools.count(1)


def to_update(raw: dict) -> dict | None:
    """Maps the vendor's frame shape to the internal bay update.

    Vendor frames look like {"device": "z12-b07", "state": "occupied", "ts": 1727600000,
    "plate": "ABC123"}; the device id encodes zone and bay.
    """
    device = raw.get("device")
    if not device or "-" not in device:
        return None
    zone_id, bay_id = device.split("-", 1)
    return {
        "zone_id": zone_id,
        "bay_id": bay_id,
        "occupied": raw.get("state") == "occupied",
        "plate": raw.get("plate", ""),
        "observed_at_ms": int(raw.get("ts", 0)) * 1000,
        "sequence": str(next(_seq)),
    }
