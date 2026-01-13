def normalization_banner_text(vehicle_count_mode: str | None, lang: str = "en") -> str | None:
    """Return a UI banner string when vehicle counts are normalized per probe."""
    if vehicle_count_mode != "normalized_per_probe":
        return None

    msg = {
        "he": "מדדים מנורמלים (לכל נקודת בדיקה). הסכומים אינם מוחלטים עד שיהיו ספירות כלי־רכב מבוססות זרימה.",
        "en": "Normalized metrics (per probe). Totals are not absolute until flow-based vehicle counts are available.",
        "ar": "مقاييس مُطبَّعة (لكل نقطة قياس). الإجماليات ليست مطلقة حتى تتوفر تقديرات عدد المركبات المبنية على التدفق.",
        "ru": "Нормированные метрики (на одну точку). Итоги не абсолютны, пока нет подсчёта машин на основе потока.",
    }.get((lang or "en").lower(), None)

    return msg or "Normalized metrics (per probe). Totals are not absolute until flow-based vehicle counts are available."
