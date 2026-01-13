def normalization_banner_text(vehicle_count_mode: str | None) -> str | None:
    """Return a UI banner string when vehicle counts are normalized per probe."""
    if vehicle_count_mode == "normalized_per_probe":
        return "Normalized metrics (per probe). Totals are not absolute until flow-based vehicle counts are available."
    return None
