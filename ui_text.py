"""UI strings for the v2 dashboard (he / en / ar / ru).

Official-reference-card strings are reused verbatim from the v1 UI
(ui_text_legacy.json).
"""

import json
from pathlib import Path

_LEGACY = json.loads((Path(__file__).resolve().parent / "ui_text_legacy.json").read_text(encoding="utf-8"))

_V2 = {
    "en": {
        "app_title": "Ayalon (Highway 20) — measured traffic delay",
        "app_subtitle": "Methodology v2.0 · fixed interchange-to-interchange sections, both directions · real-time speeds only",
        "tab_now": "Now",
        "tab_stats": "Statistics (v2)",
        "tab_quality": "Data quality & archive",
        "tab_method": "Sections & methodology",
        "status_healthy": "Live: all {ok}/{total} sections measured at {time} ({age} min ago).",
        "status_partial": "Partial: {ok}/{total} sections measured in the last cycle ({time}). Missing sections are shown as such; totals use only complete directions.",
        "status_stale": "No current measurement. Newest valid measurement: {time} ({age} min ago) — shown below as historical, not as current traffic.",
        "status_no_data": "No real-time traffic measurements are available. Newest valid measurement: {time}.",
        "status_collector_down": "The collector has not run since {time}. Values are not current.",
        "status_empty": "No v2 measurements recorded yet.",
        "last_error": "Last collection error",
        "cause_no_coverage": "TomTom no longer serves traffic flow for Israel (every Israeli point returns 'Point too far from nearest existing segment' since 2026-09-15 09:42 UTC; Israel was removed from TomTom's Traffic API coverage list). Measurements resume when an alternative real-time provider (HERE Traffic v7) is configured.",
        "cause_not_configured": "No real-time traffic provider is configured.",
        "direction_northbound": "Northbound (Holon → Rokach)",
        "direction_southbound": "Southbound (Rokach → Holon)",
        "metric_travel_time": "Travel time",
        "metric_freeflow_time": "Free-flow time",
        "metric_delay": "Delay per vehicle",
        "metric_speed": "Mean speed",
        "direction_incomplete": "Not all sections of this direction have a current measurement — no corridor total shown.",
        "sections_header": "Sections",
        "col_section": "Section",
        "col_direction": "Direction",
        "col_length": "Length, m",
        "col_state": "State",
        "col_measured": "Measured (IL time)",
        "col_tt": "Travel time, s",
        "col_ff": "Free-flow, s",
        "col_delay": "Delay, s/veh",
        "col_speed": "Speed, km/h",
        "col_ffspeed": "Free-flow speed, km/h",
        "col_coverage": "Coverage",
        "state_current": "current",
        "state_stale": "stale",
        "state_old": "old",
        "state_none": "no measurement",
        "last_valid_header": "Last valid measurement (historical, not current)",
        "window_label": "Period",
        "window_24h": "Last 24 h",
        "window_7d": "Last 7 days",
        "window_30d": "Last 30 days",
        "window_all": "All v2 data",
        "stats_no_data": "No valid v2 measurements in this period.",
        "stats_observed": "Measured time",
        "stats_coverage": "Coverage of period",
        "stats_mean_delay": "Mean delay per vehicle",
        "stats_max_delay": "Max delay per vehicle",
        "stats_congested": "Congested time (delay > 25% of free-flow)",
        "stats_caption": "Time-weighted: each measurement is valid until the next one (max {hold} min). Gaps without measurements are not filled and are reported as missing coverage.",
        "daily_header": "Daily summary (corridor, per direction)",
        "chart_header": "Corridor delay per vehicle over time",
        "econ_header": "Vehicle-hours, fuel, CO₂ and cost",
        "econ_unavailable": "Not published: these totals require the number of vehicles, which no connected source measures. The previous figures (v1) assumed vehicles = speed × 25 veh/km and are withdrawn. They will be shown once a documented traffic-volume source is configured.",
        "econ_estimate_note": "Model estimate. Volumes: {source} ({citation}). Fuel = vehicle-hours × 0.8 L/h × 1.5; CO₂ = 2.31 kg/L.",
        "econ_vh": "Vehicle-hours of delay",
        "econ_fuel": "Excess fuel, L",
        "econ_co2": "CO₂, kg",
        "econ_cost": "Fuel cost, ₪",
        "econ_time": "Time value, ₪",
        "quality_periods_header": "Periods with known data problems",
        "col_period": "Period",
        "col_severity": "Severity",
        "col_description": "Description",
        "cycles_header": "Recent collection cycles",
        "v1_header": "Archive: methodology v1 (Jan–Sep 2026) — not valid",
        "v1_body": (
            "The v1 figures are kept for audit but are not a measurement of congestion losses:\n"
            "- travel time of a 9–18 km provider segment was compared with the free-flow time of a 0.4–1.1 km window, so ~858 vehicle-hours were reported even at free flow;\n"
            "- vehicle numbers were speed × 25 veh/km, not measurements;\n"
            "- probe 'la_guardia' measured Route 44, not Ayalon; 'ha_shalom' and 'arlozorov' reused one TomTom measurement; the southbound carriageway was never measured;\n"
            "- the dashboard summed 5-minute snapshots, so totals grew with the number of API calls;\n"
            "- {reuse} runs re-recorded an old cached response (incl. 281 after the TomTom failure on 2026-09-15)."
        ),
        "v1_counts": "{runs} v1 runs ({first} … {last}); flagged cache re-use: {reuse}; stale source: {stale}.",
        "v1_download": "Download v1 archive with quality flags (CSV)",
        "method_header": "How the measurement works",
        "method_body": (
            "1. Six fixed sections of Highway 20 between the Holon, La Guardia, Arlozorov and Rokach interchanges, "
            "separately for each carriageway (geometry: OpenStreetMap, ODbL).\n"
            "2. The collector requests real-time flow every 5 minutes. Only real-time speeds are accepted "
            "(HERE: confidence > 0.7); historical profiles and speed limits are rejected.\n"
            "3. Provider geometry is matched to each section in 10 m bins (max 20 m lateral offset, same driving direction). "
            "Travel time and free-flow time are integrated over the same covered bins; at least 80% coverage is required.\n"
            "4. Delay per vehicle = max(0, travel time − free-flow time). At free flow the delay is zero.\n"
            "5. Statistics are time-weighted; missing periods are shown, never filled."
        ),
        "sections_def_header": "Section definitions",
        "map_header": "Sections map",
        "sources_header": "Other inputs",
        "provider_header": "Traffic provider",
        "no_value": "—",
    },
    "ru": {
        "app_title": "Аялон (шоссе 20) — измеренные задержки движения",
        "app_subtitle": "Методика v2.0 · фиксированные участки между развязками, оба направления · только данные реального времени",
        "tab_now": "Сейчас",
        "tab_stats": "Статистика (v2)",
        "tab_quality": "Качество данных и архив",
        "tab_method": "Участки и методика",
        "status_healthy": "Данные актуальны: измерены все {ok}/{total} участков в {time} ({age} мин назад).",
        "status_partial": "Неполный цикл: измерено {ok}/{total} участков в последнем цикле ({time}). Отсутствующие участки отмечены; итоги считаются только по полностью измеренным направлениям.",
        "status_stale": "Актуальных измерений нет. Последнее достоверное измерение: {time} ({age} мин назад) — ниже показано как историческое, а не текущее.",
        "status_no_data": "Измерений дорожного движения в реальном времени нет. Последнее достоверное измерение: {time}.",
        "status_collector_down": "Сборщик не запускался с {time}. Данные не актуальны.",
        "status_empty": "Измерения v2 ещё не записаны.",
        "last_error": "Последняя ошибка сбора",
        "cause_no_coverage": "TomTom больше не отдаёт данные о потоке для Израиля (с 15.09.2026 09:42 UTC любая точка в Израиле возвращает «Point too far from nearest existing segment»; Израиль исключён из списка покрытия TomTom Traffic API). Измерения возобновятся после подключения альтернативного источника реального времени (HERE Traffic v7).",
        "cause_not_configured": "Источник данных реального времени не настроен.",
        "direction_northbound": "На север (Холон → Роках)",
        "direction_southbound": "На юг (Роках → Холон)",
        "metric_travel_time": "Время в пути",
        "metric_freeflow_time": "Время при свободном движении",
        "metric_delay": "Задержка на автомобиль",
        "metric_speed": "Средняя скорость",
        "direction_incomplete": "Не для всех участков этого направления есть актуальное измерение — итог по коридору не показывается.",
        "sections_header": "Участки",
        "col_section": "Участок",
        "col_direction": "Направление",
        "col_length": "Длина, м",
        "col_state": "Состояние",
        "col_measured": "Измерено (время IL)",
        "col_tt": "Время в пути, с",
        "col_ff": "Свободное, с",
        "col_delay": "Задержка, с/авто",
        "col_speed": "Скорость, км/ч",
        "col_ffspeed": "Свободная скорость, км/ч",
        "col_coverage": "Покрытие",
        "state_current": "актуально",
        "state_stale": "устарело",
        "state_old": "старое",
        "state_none": "нет измерения",
        "last_valid_header": "Последнее достоверное измерение (историческое, не текущее)",
        "window_label": "Период",
        "window_24h": "24 часа",
        "window_7d": "7 дней",
        "window_30d": "30 дней",
        "window_all": "Все данные v2",
        "stats_no_data": "За этот период нет достоверных измерений v2.",
        "stats_observed": "Измеренное время",
        "stats_coverage": "Покрытие периода",
        "stats_mean_delay": "Средняя задержка на авто",
        "stats_max_delay": "Макс. задержка на авто",
        "stats_congested": "Время затора (задержка > 25% от свободного)",
        "stats_caption": "Взвешено по времени: каждое измерение действует до следующего (не дольше {hold} мин). Пропуски не заполняются и учитываются как отсутствие покрытия.",
        "daily_header": "Сводка по дням (коридор, по направлениям)",
        "chart_header": "Задержка на автомобиль по коридору во времени",
        "econ_header": "Автомобиле-часы, топливо, CO₂ и стоимость",
        "econ_unavailable": "Не публикуется: для этих итогов нужно число автомобилей, а ни один подключённый источник его не измеряет. Прежние значения (v1) предполагали «автомобили = скорость × 25 авт/км» и отозваны. Показатели появятся после подключения документированного источника интенсивности движения.",
        "econ_estimate_note": "Модельная оценка. Интенсивность: {source} ({citation}). Топливо = авто-часы × 0,8 л/ч × 1,5; CO₂ = 2,31 кг/л.",
        "econ_vh": "Автомобиле-часы задержки",
        "econ_fuel": "Лишнее топливо, л",
        "econ_co2": "CO₂, кг",
        "econ_cost": "Стоимость топлива, ₪",
        "econ_time": "Стоимость времени, ₪",
        "quality_periods_header": "Периоды с известными проблемами данных",
        "col_period": "Период",
        "col_severity": "Серьёзность",
        "col_description": "Описание",
        "cycles_header": "Последние циклы сбора",
        "v1_header": "Архив: методика v1 (янв–сен 2026) — недостоверно",
        "v1_body": (
            "Данные v1 сохранены для проверки, но не являются измерением потерь от заторов:\n"
            "- время проезда сегмента поставщика длиной 9–18 км сравнивалось со временем свободного движения по окну 0,4–1,1 км, поэтому даже при свободном движении показывалось ~858 авто-часов;\n"
            "- число автомобилей = скорость × 25 авт/км, а не измерение;\n"
            "- точка «la_guardia» измеряла шоссе 44, а не Аялон; «ha_shalom» и «arlozorov» использовали одно и то же измерение TomTom; южное направление не измерялось вовсе;\n"
            "- интерфейс суммировал 5-минутные снимки, поэтому итоги росли с числом запросов к API;\n"
            "- {reuse} записей повторно записали старый кэшированный ответ (в т.ч. 281 после отказа TomTom 15.09.2026)."
        ),
        "v1_counts": "{runs} записей v1 ({first} … {last}); повтор кэша: {reuse}; устаревший источник: {stale}.",
        "v1_download": "Скачать архив v1 с отметками качества (CSV)",
        "method_header": "Как устроено измерение",
        "method_body": (
            "1. Шесть фиксированных участков шоссе 20 между развязками Холон, Ла-Гуардия, Арлозоров и Роках, "
            "отдельно для каждой проезжей части (геометрия: OpenStreetMap, ODbL).\n"
            "2. Сборщик каждые 5 минут запрашивает поток в реальном времени. Принимаются только скорости реального времени "
            "(HERE: confidence > 0,7); исторические профили и ограничения скорости отбрасываются.\n"
            "3. Геометрия поставщика сопоставляется с каждым участком по ячейкам 10 м (смещение не более 20 м, то же направление). "
            "Время в пути и время свободного движения интегрируются по одним и тем же ячейкам; требуется покрытие не менее 80%.\n"
            "4. Задержка на автомобиль = max(0, время в пути − время свободного движения). При свободном движении задержка равна нулю.\n"
            "5. Статистика взвешена по времени; пропуски показываются, а не заполняются."
        ),
        "sections_def_header": "Определения участков",
        "map_header": "Карта участков",
        "sources_header": "Прочие входные данные",
        "provider_header": "Источник данных о движении",
        "no_value": "—",
    },
    "he": {
        "app_title": "איילון (כביש 20) — עיכובי תנועה מדודים",
        "app_subtitle": "מתודולוגיה v2.0 · קטעים קבועים בין מחלפים, בשני הכיוונים · נתוני זמן אמת בלבד",
        "tab_now": "עכשיו",
        "tab_stats": "סטטיסטיקה (v2)",
        "tab_quality": "איכות נתונים וארכיון",
        "tab_method": "קטעים ומתודולוגיה",
        "status_healthy": "נתונים עדכניים: כל {ok}/{total} הקטעים נמדדו ב-{time} (לפני {age} דק׳).",
        "status_partial": "מחזור חלקי: {ok}/{total} קטעים נמדדו במחזור האחרון ({time}). קטעים חסרים מסומנים; סיכומים מחושבים רק לכיוונים שנמדדו במלואם.",
        "status_stale": "אין מדידה עדכנית. המדידה התקפה האחרונה: {time} (לפני {age} דק׳) — מוצגת למטה כהיסטורית, לא כמצב תנועה נוכחי.",
        "status_no_data": "אין מדידות תנועה בזמן אמת. המדידה התקפה האחרונה: {time}.",
        "status_collector_down": "האוסף לא רץ מאז {time}. הנתונים אינם עדכניים.",
        "status_empty": "טרם נרשמו מדידות v2.",
        "last_error": "שגיאת האיסוף האחרונה",
        "cause_no_coverage": "TomTom הפסיקה לספק נתוני זרימת תנועה לישראל (מאז 15.09.2026 09:42 UTC כל נקודה בישראל מחזירה ‎'Point too far from nearest existing segment'‎; ישראל הוסרה מרשימת הכיסוי של TomTom Traffic API). המדידות יתחדשו לאחר חיבור ספק חלופי בזמן אמת (HERE Traffic v7).",
        "cause_not_configured": "לא הוגדר ספק נתוני תנועה בזמן אמת.",
        "direction_northbound": "צפונה (חולון ← רוקח)",
        "direction_southbound": "דרומה (רוקח ← חולון)",
        "metric_travel_time": "זמן נסיעה",
        "metric_freeflow_time": "זמן בזרימה חופשית",
        "metric_delay": "עיכוב לרכב",
        "metric_speed": "מהירות ממוצעת",
        "direction_incomplete": "לא לכל הקטעים בכיוון זה יש מדידה עדכנית — סיכום המסדרון אינו מוצג.",
        "sections_header": "קטעים",
        "col_section": "קטע",
        "col_direction": "כיוון",
        "col_length": "אורך, מ׳",
        "col_state": "מצב",
        "col_measured": "נמדד (שעון ישראל)",
        "col_tt": "זמן נסיעה, שנ׳",
        "col_ff": "זרימה חופשית, שנ׳",
        "col_delay": "עיכוב, שנ׳/רכב",
        "col_speed": "מהירות, קמ״ש",
        "col_ffspeed": "מהירות חופשית, קמ״ש",
        "col_coverage": "כיסוי",
        "state_current": "עדכני",
        "state_stale": "לא עדכני",
        "state_old": "ישן",
        "state_none": "אין מדידה",
        "last_valid_header": "המדידה התקפה האחרונה (היסטורית, לא נוכחית)",
        "window_label": "תקופה",
        "window_24h": "24 שעות",
        "window_7d": "7 ימים",
        "window_30d": "30 ימים",
        "window_all": "כל נתוני v2",
        "stats_no_data": "אין מדידות v2 תקפות בתקופה זו.",
        "stats_observed": "זמן מדוד",
        "stats_coverage": "כיסוי התקופה",
        "stats_mean_delay": "עיכוב ממוצע לרכב",
        "stats_max_delay": "עיכוב מרבי לרכב",
        "stats_congested": "זמן עומס (עיכוב > 25% מזמן הזרימה החופשית)",
        "stats_caption": "משוקלל בזמן: כל מדידה תקפה עד הבאה (לכל היותר {hold} דק׳). פערים אינם ממולאים ומדווחים ככיסוי חסר.",
        "daily_header": "סיכום יומי (מסדרון, לפי כיוון)",
        "chart_header": "עיכוב לרכב לאורך המסדרון לאורך זמן",
        "econ_header": "שעות-רכב, דלק, CO₂ ועלות",
        "econ_unavailable": "לא מתפרסם: סיכומים אלה דורשים את מספר כלי הרכב, ואף מקור מחובר אינו מודד אותו. הערכים הקודמים (v1) הניחו ״רכבים = מהירות × 25 רכב/ק״מ״ ובוטלו. הם יוצגו לאחר חיבור מקור מתועד לנפחי תנועה.",
        "econ_estimate_note": "הערכת מודל. נפחים: {source} ({citation}). דלק = שעות-רכב × 0.8 ל׳/ש׳ × 1.5; CO₂ = 2.31 ק״ג/ל׳.",
        "econ_vh": "שעות-רכב של עיכוב",
        "econ_fuel": "דלק עודף, ל׳",
        "econ_co2": "CO₂, ק״ג",
        "econ_cost": "עלות דלק, ₪",
        "econ_time": "ערך זמן, ₪",
        "quality_periods_header": "תקופות עם בעיות נתונים ידועות",
        "col_period": "תקופה",
        "col_severity": "חומרה",
        "col_description": "תיאור",
        "cycles_header": "מחזורי איסוף אחרונים",
        "v1_header": "ארכיון: מתודולוגיה v1 (ינו׳–ספט׳ 2026) — לא תקף",
        "v1_body": (
            "נתוני v1 נשמרים לביקורת אך אינם מדידה של הפסדי עומס:\n"
            "- זמן הנסיעה של מקטע ספק באורך 9–18 ק״מ הושווה לזמן זרימה חופשית של חלון באורך 0.4–1.1 ק״מ, ולכן דווחו ~858 שעות-רכב גם בזרימה חופשית;\n"
            "- מספר כלי הרכב = מהירות × 25 רכב/ק״מ, לא מדידה;\n"
            "- הנקודה 'la_guardia' מדדה את כביש 44 ולא את איילון; 'ha_shalom' ו-'arlozorov' השתמשו באותה מדידת TomTom; הכיוון דרומה לא נמדד כלל;\n"
            "- הממשק סכם תמונות מצב של 5 דקות, כך שהסיכומים גדלו עם מספר הקריאות ל-API;\n"
            "- {reuse} רשומות רשמו מחדש תשובה ישנה מהמטמון (כולל 281 לאחר תקלת TomTom ב-15.09.2026)."
        ),
        "v1_counts": "{runs} רשומות v1 ({first} … {last}); שימוש חוזר במטמון: {reuse}; מקור לא עדכני: {stale}.",
        "v1_download": "הורדת ארכיון v1 עם סימוני איכות (CSV)",
        "method_header": "כיצד פועלת המדידה",
        "method_body": (
            "1. שישה קטעים קבועים של כביש 20 בין מחלפי חולון, לה גארדיה, ארלוזורוב ורוקח, "
            "בנפרד לכל מסלול (גאומטריה: OpenStreetMap, ODbL).\n"
            "2. האוסף מבקש נתוני זרימה בזמן אמת כל 5 דקות. מתקבלות רק מהירויות בזמן אמת "
            "(HERE: confidence > 0.7); פרופילים היסטוריים ומהירויות מותרות נדחים.\n"
            "3. גאומטריית הספק מותאמת לכל קטע בתאים של 10 מ׳ (סטייה עד 20 מ׳, אותו כיוון נסיעה). "
            "זמן הנסיעה וזמן הזרימה החופשית מחושבים על אותם תאים; נדרש כיסוי של 80% לפחות.\n"
            "4. עיכוב לרכב = max(0, זמן נסיעה − זמן זרימה חופשית). בזרימה חופשית העיכוב הוא אפס.\n"
            "5. הסטטיסטיקה משוקללת בזמן; פערים מוצגים ואינם ממולאים."
        ),
        "sections_def_header": "הגדרות הקטעים",
        "map_header": "מפת הקטעים",
        "sources_header": "קלטים נוספים",
        "provider_header": "ספק נתוני תנועה",
        "no_value": "—",
    },
    "ar": {
        "app_title": "أيالون (الطريق 20) — تأخير حركة المرور المُقاس",
        "app_subtitle": "المنهجية v2.0 · مقاطع ثابتة بين التقاطعات، في الاتجاهين · بيانات الزمن الحقيقي فقط",
        "tab_now": "الآن",
        "tab_stats": "إحصاءات (v2)",
        "tab_quality": "جودة البيانات والأرشيف",
        "tab_method": "المقاطع والمنهجية",
        "status_healthy": "بيانات حالية: تم قياس جميع المقاطع {ok}/{total} في {time} (قبل {age} دقيقة).",
        "status_partial": "دورة جزئية: تم قياس {ok}/{total} مقاطع في الدورة الأخيرة ({time}). المقاطع الناقصة مُعلَّمة؛ الإجماليات تُحسب فقط للاتجاهات المقاسة بالكامل.",
        "status_stale": "لا يوجد قياس حالي. آخر قياس صالح: {time} (قبل {age} دقيقة) — يُعرض أدناه كقياس تاريخي وليس كحالة المرور الحالية.",
        "status_no_data": "لا تتوفر قياسات مرور في الزمن الحقيقي. آخر قياس صالح: {time}.",
        "status_collector_down": "لم يعمل المُجمِّع منذ {time}. القيم ليست حالية.",
        "status_empty": "لم تُسجَّل قياسات v2 بعد.",
        "last_error": "آخر خطأ في الجمع",
        "cause_no_coverage": "توقفت TomTom عن تقديم بيانات تدفق المرور لإسرائيل (منذ 15.09.2026 09:42 UTC تُرجع كل نقطة في إسرائيل ‎'Point too far from nearest existing segment'‎؛ وأُزيلت إسرائيل من قائمة تغطية TomTom Traffic API). ستُستأنف القياسات بعد ربط مزوّد بديل في الزمن الحقيقي (HERE Traffic v7).",
        "cause_not_configured": "لم يتم إعداد مزوّد بيانات مرور في الزمن الحقيقي.",
        "direction_northbound": "شمالًا (حولون ← روكاح)",
        "direction_southbound": "جنوبًا (روكاح ← حولون)",
        "metric_travel_time": "زمن الرحلة",
        "metric_freeflow_time": "زمن التدفق الحر",
        "metric_delay": "التأخير لكل مركبة",
        "metric_speed": "متوسط السرعة",
        "direction_incomplete": "ليست كل مقاطع هذا الاتجاه ذات قياس حالي — لا يُعرض إجمالي الممر.",
        "sections_header": "المقاطع",
        "col_section": "المقطع",
        "col_direction": "الاتجاه",
        "col_length": "الطول، م",
        "col_state": "الحالة",
        "col_measured": "وقت القياس (توقيت إسرائيل)",
        "col_tt": "زمن الرحلة، ث",
        "col_ff": "التدفق الحر، ث",
        "col_delay": "التأخير، ث/مركبة",
        "col_speed": "السرعة، كم/س",
        "col_ffspeed": "سرعة التدفق الحر، كم/س",
        "col_coverage": "التغطية",
        "state_current": "حالي",
        "state_stale": "قديم",
        "state_old": "قديم جدًا",
        "state_none": "لا يوجد قياس",
        "last_valid_header": "آخر قياس صالح (تاريخي، ليس حاليًا)",
        "window_label": "الفترة",
        "window_24h": "24 ساعة",
        "window_7d": "7 أيام",
        "window_30d": "30 يومًا",
        "window_all": "كل بيانات v2",
        "stats_no_data": "لا توجد قياسات v2 صالحة في هذه الفترة.",
        "stats_observed": "الوقت المُقاس",
        "stats_coverage": "تغطية الفترة",
        "stats_mean_delay": "متوسط التأخير لكل مركبة",
        "stats_max_delay": "أقصى تأخير لكل مركبة",
        "stats_congested": "وقت الازدحام (تأخير > 25% من التدفق الحر)",
        "stats_caption": "مرجّح بالزمن: كل قياس صالح حتى القياس التالي (بحد أقصى {hold} دقيقة). الفجوات لا تُملأ وتُعرض كنقص في التغطية.",
        "daily_header": "ملخص يومي (الممر، حسب الاتجاه)",
        "chart_header": "التأخير لكل مركبة على الممر عبر الزمن",
        "econ_header": "ساعات المركبات والوقود وCO₂ والتكلفة",
        "econ_unavailable": "غير منشور: تتطلب هذه الإجماليات عدد المركبات، ولا يقيسه أي مصدر متصل. القيم السابقة (v1) افترضت «المركبات = السرعة × 25 مركبة/كم» وقد سُحبت. ستظهر بعد ربط مصدر موثّق لأحجام المرور.",
        "econ_estimate_note": "تقدير نموذجي. الأحجام: {source} ({citation}). الوقود = ساعات المركبات × 0.8 ل/س × 1.5؛ CO₂ = 2.31 كغ/ل.",
        "econ_vh": "ساعات تأخير المركبات",
        "econ_fuel": "وقود زائد، ل",
        "econ_co2": "CO₂، كغ",
        "econ_cost": "تكلفة الوقود، ₪",
        "econ_time": "قيمة الوقت، ₪",
        "quality_periods_header": "فترات ذات مشكلات بيانات معروفة",
        "col_period": "الفترة",
        "col_severity": "الخطورة",
        "col_description": "الوصف",
        "cycles_header": "دورات الجمع الأخيرة",
        "v1_header": "الأرشيف: المنهجية v1 (يناير–سبتمبر 2026) — غير صالحة",
        "v1_body": (
            "تُحفظ بيانات v1 للتدقيق لكنها ليست قياسًا لخسائر الازدحام:\n"
            "- قورن زمن رحلة مقطع مزوّد بطول 9–18 كم بزمن التدفق الحر لنافذة بطول 0.4–1.1 كم، فظهرت ~858 ساعة-مركبة حتى في التدفق الحر؛\n"
            "- عدد المركبات = السرعة × 25 مركبة/كم، وليس قياسًا؛\n"
            "- نقطة 'la_guardia' قاست الطريق 44 وليس أيالون؛ و'ha_shalom' و'arlozorov' استخدمتا قياس TomTom نفسه؛ ولم يُقَس الاتجاه الجنوبي إطلاقًا؛\n"
            "- جمعت الواجهة لقطات كل 5 دقائق، فازدادت الإجماليات مع عدد طلبات API؛\n"
            "- {reuse} سجلًا أعادت تسجيل استجابة قديمة من الذاكرة المؤقتة (منها 281 بعد عطل TomTom في 15.09.2026)."
        ),
        "v1_counts": "{runs} سجلات v1 ({first} … {last})؛ إعادة استخدام الذاكرة المؤقتة: {reuse}؛ مصدر قديم: {stale}.",
        "v1_download": "تنزيل أرشيف v1 مع علامات الجودة (CSV)",
        "method_header": "كيف يعمل القياس",
        "method_body": (
            "1. ستة مقاطع ثابتة من الطريق 20 بين تقاطعات حولون ولا غوارديا وأرلوزوروف وروكاح، "
            "لكل مسار على حدة (الهندسة: OpenStreetMap، ODbL).\n"
            "2. يطلب المُجمِّع بيانات التدفق في الزمن الحقيقي كل 5 دقائق. تُقبل سرعات الزمن الحقيقي فقط "
            "(HERE: confidence > 0.7)؛ وتُرفض الملفات التاريخية وحدود السرعة.\n"
            "3. تُطابق هندسة المزوّد مع كل مقطع بخلايا 10 م (انحراف حتى 20 م، نفس اتجاه السير). "
            "يُحسب زمن الرحلة وزمن التدفق الحر على الخلايا نفسها؛ ويلزم تغطية 80% على الأقل.\n"
            "4. التأخير لكل مركبة = max(0, زمن الرحلة − زمن التدفق الحر). في التدفق الحر يكون التأخير صفرًا.\n"
            "5. الإحصاءات مرجّحة بالزمن؛ الفجوات تُعرض ولا تُملأ."
        ),
        "sections_def_header": "تعريفات المقاطع",
        "map_header": "خريطة المقاطع",
        "sources_header": "مدخلات أخرى",
        "provider_header": "مزوّد بيانات المرور",
        "no_value": "—",
    },
}


def t(key: str, lang: str) -> str:
    lang = (lang or "en").lower()
    for table in (_V2.get(lang, {}), _LEGACY.get(lang, {}), _V2["en"], _LEGACY.get("en", {})):
        if key in table:
            return str(table[key])
    return key


LANGS = list(_V2.keys())
