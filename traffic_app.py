import os
import time
import streamlit as st
from methodology import AyalonModel
from sources import tomtom
from sources.air_quality import get_air_quality_for_ayalon, get_cached_air_quality
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l as fetch_current_fuel_price, get_cached_fuel_price
from sources.secure_config import SecureConfig
from sources.health import get_quick_status, get_quick_status_readonly, compute_traffic_health
from sources.analytics import get_dashboard_summary, record_request, record_stale_data
from sources.error_handler import ErrorHandler
from ui_messages import normalization_banner_text
from datetime import datetime
from sources.history_store import HistoryStore
from sources.official_stats import fetch_official_reference_card

# ── UI operation mode ──────────────────────────────────────────────────
# Default: "readonly" — dashboard reads only from SQLite (no TomTom API calls).
# Set AYALON_UI_MODE=live to restore the old behaviour (debug / manual testing).
_UI_MODE = os.getenv("AYALON_UI_MODE", "readonly").strip().lower()

st.set_page_config(page_title="Ayalon Real-Time Physical Impact Model", layout="wide")

LANG_CHOICES = [
    ("עברית", "he"),
    ("English", "en"),
    ("العربية", "ar"),
    ("Русский", "ru"),
]
_lang_display_to_code = {d: c for d, c in LANG_CHOICES}

_I18N = {
    "he": {
        "app_title": "מודל השפעה פיזיקלית בזמן אמת — איילון",
        "app_subtitle": "**גרסה:** 1.0 (Freeze) | **שכבה:** L5 — תחבורה / אמת פיזיקלית | **תחום:** כביש 20 (איילון), ישראל",
        "language_label": "שפה",
        "sidebar_data_refresh": "נתונים ורענון",
        "auto_refresh": "רענון אוטומטי כל 5 דקות",
        "loss_display_header": "תצוגת הפסדים",
        "loss_display_label": "הצג הפסדים כ",
        "history_window_label": "חלון היסטוריה",
        "system_health": "בריאות מערכת",
        "traffic_mode": "מצב תנועה",
        "traffic_mode_help": "בחר מאיפה להגיע נתוני התנועה: נתונים חיים (TomTom) או נתוני הדגמה (מדומים).",
        "traffic_mode_opt_flow": "חי (TomTom)",
        "traffic_mode_opt_sample": "הדגמה (Sample)",
        "tab_dashboard": "לוח מחוונים",
        "tab_history": "היסטוריה וסטטיסטיקה",
        "tab_sources": "מקורות ובריאות",

        "input_sources_header": "מקורות נתונים נכנסים",
        "system_header": "מערכת",
        "traffic_source": "מקור תנועה",
        "air_quality_source": "מקור איכות אוויר",
        "fuel_price_source": "מקור מחיר דלק",
        "updated": "עודכן",
        "price_ils_per_l": "מחיר (ש״ח/ליטר)",
        "traffic_age": "גיל נתוני תנועה",
        "no_segments": "אין קטעי תנועה זמינים; בדוק הגדרות או רשת",
        "losses_explained": "הפסדים — הסבר",
        "what_mean": "מה המשמעות של המספרים האלה (בשפה פשוטה)",
        "what_mean_body": "- שעות-רכב (עיכוב): זמן עודף כולל שכלי רכב מבלים עקב עומס לעומת זרימה חופשית.\n- דלק עודף (ל׳): דלק נוסף שנשרף בזמן עיכוב (סרק/עצור-וסע).\n- CO₂ (ק״ג): פליטות הנגזרות מהדלק העודף (2.31 ק״ג CO₂ לליטר).\n- עלות דלק ישירה (ש״ח): הדלק העודף כפול מחיר הדלק הנוכחי.\nאלו מונים מערכתיים: מתארים השפעה כוללת, לא נהג יחיד.",
        "provenance": "מקוריות (Provenance)",
        "model_version": "גרסת מודל",
        "constants_version": "גרסת קבועים",
        "data_timestamp": "חותמת זמן של הנתונים",
        "pipeline_run_id": "מזהה ריצה",
        "stale_warning": "נתוני התנועה מיושנים (יותר מפי 2 מהקצב)",
        "waiting_inputs": "ממתין למחיר דלק תקין או להזנת תנועה. אפשר להגדיר FUEL_PRICE_ILS כגיבוי.",
        "history_header": "היסטוריה וסטטיסטיקה",
        "history_caption": "נשמר מקומית בזמן הניטור (SQLite).",
        "no_history": "עדיין אין היסטוריה. הפעל רענון אוטומטי או הרץ כמה פעמים.",
        "summary": "סיכום",
        "trend": "מגמה",
        "table": "טבלה",
        "download_csv": "הורד CSV",
        "history_render_fail": "יש היסטוריה אך לא ניתן להציג אותה כטבלה בסביבה זו.",
        "modeling_note": "**הערת מידול:** המודל אוכף סכימת קטעים קנונית ומצרף מקוריות לכל ריצה.",
        "data_sources_footer": "מקורות נתונים: TomTom Traffic Flow (v4) לתנועה, Sviva לאיכות אוויר, ומקורות ממשלתיים למחיר הדלק. קצב עדכון ~5 דקות (TTL מטמון). ספירות כלי רכב *מוערכות* מזרימה/מהירות ואינן מונה רשמי.",

        "loss_opt_per_hour": "לשעה",
        "loss_opt_per_day": "ליום",
        "loss_opt_per_year": "לשנה",
        "loss_opt_total_window": "סה\"כ (לחלון)",
        "window_opt_1h": "שעה אחרונה",
        "window_opt_24h": "24 שעות אחרונות",
        "window_opt_7d": "7 ימים אחרונים",
        "window_opt_30d": "30 ימים אחרונים",
        "window_opt_all": "כל הזמן",
        "metric_vehicle_hours": "שעות-רכב",
        "metric_co2": "CO₂",
        "metric_excess_fuel": "דלק עודף",
        "metric_fuel_cost": "עלות דלק",
        "trend_chart_caption": "מקרא צבעים בגרף: כחול = עלות דלק (₪), כתום = CO₂ (ק״ג), ירוק = שעות-רכב (עיכוב).",
        "series_fuel_cost": "עלות דלק (₪)",
        "series_co2": "CO₂ (ק״ג)",
        "series_vehicle_hours": "שעות-רכב (עיכוב)",

        "success_rate": "שיעור הצלחה",
        "cache_hit_ratio": "יחס פגיעות במטמון",
        "errors_session": "שגיאות (בסשן)",

        "download_xlsx": "הורד Excel",
        "export_note": "הייצוא כולל את הטבלה והגרפים (מסוכמים לפי אותו חלון/סקאלה).",
        "time_value_caption": "אומדן עלות זמן (₪): ₪ {value:,.0f} (בהנחה ₪{rate:.2f}/שעת-רכב)",
        "extrapolated_caption": "הוחשב בהסקה מ-{window}. משך נצפה: {hours:.2f} שעות.",

        "official_card_title": "ייחוס רשמי — כקונטקסט בלבד",
        "official_card_subtitle_context_only": "מסגרת ייחוס (reference-only): מקור רשמי מצוטט לצורך הקשר, לא מדד אמת.",
        "official_not_configured": "מקור רשמי מומלץ (reference-only) מארכיון מבקר המדינה: דו\"ח מבקר המדינה — Abstracts\nhttps://library.mevaker.gov.il/sites/DigitalLibrary/Documents/2024/2024.11-75A-PartB/EN/2024.11-75A-PartB-All-Abstracts-EN.pdf\nאפשר להשתמש בקישור הזה כ- OFFICIAL_REPORT_URL ולהגדיר OFFICIAL_SOURCE_LABEL / OFFICIAL_REPORT_YEAR / OFFICIAL_METRIC_LABEL / OFFICIAL_VALUE / OFFICIAL_UNIT (למשל ILS_per_year).",
        "official_source_label": "מקור",
        "official_report_year": "שנת דו\"ח",
        "official_value_year": "שנת הערכה",
        "official_metric_label": "מדד",
        "official_value_label": "ערך",
        "official_unit_ils_per_year": "ש\"ח לשנה",
        "official_metric_state_comptroller_congestion_cost": "הערכת נזק כלכלי שנתי מעומסי תנועה",
        "official_disclaimer_not_comparable": "אין מקור ממשלתי ציבורי שמספק אנלוג ישיר ל\"מונה חי\" ברמת מסדרון ב-vehicle-hours; לכן הייחוס הרשמי מוצג כאן כערך שנתי/מצרפי לצורך הקשר בלבד.",
        "official_disclaimer_planning_basis": "היעדר אנלוג ציבורי ישיר אינו מעיד על היעדר כלי תכנון: תכנון תחבורתי נשען לרוב על מודלים מצרפיים, סקרים, נתוני חיישנים/מפעילים והערכות כלכליות — אך בפרסומים לציבור הם מוצגים בדרך כלל כמדדים שנתיים/מצרפיים ולא כמונה חי לפי מסדרון.",
    },
    "en": {
        "app_title": "Ayalon Real-Time Physical Impact Model — Monitor",
        "app_subtitle": "**Version:** 1.0 (Freeze) | **Layer:** L5 — Transport / Physical Truth | **Scope:** Highway 20 (Ayalon), Israel",
        "language_label": "Language",
        "sidebar_data_refresh": "Data & Refresh",
        "auto_refresh": "Auto-refresh every 5 minutes",
        "loss_display_header": "Loss Display",
        "loss_display_label": "Show losses as",
        "history_window_label": "History window",
        "system_health": "System health",
        "traffic_mode": "Traffic mode",
        "traffic_mode_help": "Choose where the traffic data comes from: live TomTom traffic, or demo (synthetic) sample data.",
        "traffic_mode_opt_flow": "Live (TomTom)",
        "traffic_mode_opt_sample": "Demo (sample)",
        "tab_dashboard": "Dashboard",
        "tab_history": "History & Stats",
        "tab_sources": "Sources & Health",

        "input_sources_header": "Input Data Sources",
        "system_header": "System",
        "traffic_source": "Traffic Source",
        "air_quality_source": "Air Quality Source",
        "fuel_price_source": "Fuel Price Source",
        "updated": "Updated",
        "price_ils_per_l": "Price (ILS/L)",
        "traffic_age": "Traffic age",
        "no_segments": "No traffic segments available; check configuration or network",
        "losses_explained": "Losses — explained",
        "what_mean": "What these numbers mean (plain language)",
        "what_mean_body": "- Vehicle-Hours (delay): total extra time all vehicles spend due to congestion vs free-flow.\n- Excess fuel (L): extra fuel burned while delayed (idle/stop-go).\n- CO₂ (kg): emissions implied by that extra fuel (using 2.31 kg CO₂ per liter).\n- Direct fuel cost (₪): fuel excess multiplied by current fuel price (ILS/L).\nThese are system-level counters: they describe total impact, not a single driver.",
        "provenance": "Provenance",
        "model_version": "Model version",
        "constants_version": "Constants version",
        "data_timestamp": "Data timestamp",
        "pipeline_run_id": "Pipeline run id",
        "stale_warning": "Traffic data is STALE (older than 2×cadence)",
        "waiting_inputs": "Waiting for valid fuel price or traffic feed. Set FUEL_PRICE_ILS env var as fallback.",
        "history_header": "History & Statistics",
        "history_caption": "Saved locally during monitoring (SQLite).",
        "no_history": "No history yet. Enable auto-refresh or rerun a few times.",
        "summary": "Summary",
        "trend": "Trend",
        "table": "Table",
        "download_csv": "Download CSV",
        "history_render_fail": "History is available but could not be rendered as a table in this environment.",
        "modeling_note": "**Modeling Note:** This model enforces canonical segment schema and attaches provenance to each run.",
        "data_sources_footer": "Data sources: TomTom Traffic Flow (v4) for traffic, Sviva API for air quality, and government sources for fuel price. Update cadence is ~5 minutes (cache TTL). Vehicle counts are *estimated* from flow/speed and are not an official vehicle counter.",

        "loss_opt_per_hour": "Per hour",
        "loss_opt_per_day": "Per day",
        "loss_opt_per_year": "Per year",
        "loss_opt_total_window": "Total (window)",
        "window_opt_1h": "Last 1 hour",
        "window_opt_24h": "Last 24 hours",
        "window_opt_7d": "Last 7 days",
        "window_opt_30d": "Last 30 days",
        "window_opt_all": "All time",
        "metric_vehicle_hours": "Vehicle-Hours",
        "metric_co2": "CO₂",
        "metric_excess_fuel": "Excess fuel",
        "metric_fuel_cost": "Fuel cost",
        "trend_chart_caption": "Chart legend by color: blue = fuel cost (₪), orange = CO₂ (kg), green = vehicle-hours (delay).",
        "series_fuel_cost": "Fuel cost (₪)",
        "series_co2": "CO₂ (kg)",
        "series_vehicle_hours": "Vehicle-hours (delay)",

        "success_rate": "Success rate",
        "cache_hit_ratio": "Cache hit ratio",
        "errors_session": "Errors (session)",

        "download_xlsx": "Download Excel",
        "export_note": "Export includes the table and charts (aggregated by the same window/scale).",
        "time_value_caption": "Indicative time-value loss (₪): ₪ {value:,.0f} (assumes ₪{rate:.2f}/vehicle-hour)",
        "extrapolated_caption": "Extrapolated from {window}. Observed duration: {hours:.2f} hours.",

        "official_card_title": "Official reference — context only",
        "official_card_subtitle_context_only": "Reference-only: a cited official number for context, not a truth-source validator.",
        "official_not_configured": "Recommended official PDF source (reference-only) from the State Comptroller archive: State Comptroller Report — Abstracts\nhttps://library.mevaker.gov.il/sites/DigitalLibrary/Documents/2024/2024.11-75A-PartB/EN/2024.11-75A-PartB-All-Abstracts-EN.pdf\nUse this URL as OFFICIAL_REPORT_URL and set OFFICIAL_SOURCE_LABEL / OFFICIAL_REPORT_YEAR / OFFICIAL_METRIC_LABEL / OFFICIAL_VALUE / OFFICIAL_UNIT (e.g., ILS_per_year).",
        "official_source_label": "Source",
        "official_report_year": "Report year",
        "official_value_year": "Value year",
        "official_metric_label": "Metric",
        "official_value_label": "Value",
        "official_unit_ils_per_year": "ILS per year",
        "official_metric_state_comptroller_congestion_cost": "Estimated annual economic cost of road congestion",
        "official_disclaimer_not_comparable": "Public government sources typically do not provide a direct analogue to a live, corridor-level vehicle-hours counter; therefore this official reference is shown as an annual/aggregate context value only.",
        "official_disclaimer_planning_basis": "Lack of a public direct analogue does not imply lack of planning tools: transport planning commonly relies on aggregated models, surveys, sensor/operator data, and economic assessments, but public releases are usually annual/aggregate indicators rather than a live corridor vehicle-hours counter.",
    },
    "ar": {
        "app_title": "نموذج الأثر الفيزيائي اللحظي — أيالون",
        "app_subtitle": "**الإصدار:** 1.0 (Freeze) | **الطبقة:** L5 — النقل / الحقيقة الفيزيائية | **النطاق:** الطريق السريع 20 (أيالون)، إسرائيل",
        "language_label": "اللغة",
        "sidebar_data_refresh": "البيانات والتحديث",
        "auto_refresh": "تحديث تلقائي كل 5 دقائق",
        "loss_display_header": "عرض الخسائر",
        "loss_display_label": "اعرض الخسائر كـ",
        "history_window_label": "نافذة السجل",
        "system_health": "صحة النظام",
        "traffic_mode": "وضع المرور",
        "traffic_mode_help": "اختر مصدر بيانات المرور: بيانات مباشرة (TomTom) أو بيانات تجريبية (Sample) للعرض.",
        "traffic_mode_opt_flow": "مباشر (TomTom)",
        "traffic_mode_opt_sample": "تجريبي (Sample)",
        "tab_dashboard": "لوحة التحكم",
        "tab_history": "السجل والإحصاءات",
        "tab_sources": "المصادر والصحة",

        "input_sources_header": "مصادر البيانات",
        "system_header": "النظام",
        "traffic_source": "مصدر المرور",
        "air_quality_source": "مصدر جودة الهواء",
        "fuel_price_source": "مصدر سعر الوقود",
        "updated": "آخر تحديث",
        "price_ils_per_l": "السعر (شيكل/لتر)",
        "traffic_age": "عمر بيانات المرور",
        "no_segments": "لا توجد مقاطع مرور متاحة؛ تحقّق من الإعدادات أو الشبكة",
        "losses_explained": "الخسائر — شرح",
        "what_mean": "ماذا تعني هذه الأرقام (بلغة بسيطة)",
        "what_mean_body": "- ساعات-مركبة (تأخير): مجموع الوقت الإضافي الذي تقضيه كل المركبات بسبب الازدحام مقارنةً بالتدفق الحر.\n- وقود زائد (لتر): وقود إضافي يُحرق أثناء التأخير (توقف/انطلاق).\n- CO₂ (كغ): الانبعاثات الناتجة عن هذا الوقود الزائد (2.31 كغ CO₂ لكل لتر).\n- تكلفة الوقود المباشرة (₪): الوقود الزائد مضروبًا في سعر الوقود الحالي.\nهذه عدّادات على مستوى النظام: تصف الأثر الكلي وليس سائقًا واحدًا.",
        "provenance": "المصدرية (Provenance)",
        "model_version": "إصدار النموذج",
        "constants_version": "إصدار الثوابت",
        "data_timestamp": "طابع وقت البيانات",
        "pipeline_run_id": "معرّف التشغيل",
        "stale_warning": "بيانات المرور قديمة (أكثر من ضعفي الوتيرة)",
        "waiting_inputs": "بانتظار سعر وقود صالح أو بيانات المرور. يمكن ضبط FUEL_PRICE_ILS كخيار احتياطي.",
        "history_header": "السجل والإحصاءات",
        "history_caption": "يُحفظ محليًا أثناء المراقبة (SQLite).",
        "no_history": "لا يوجد سجل بعد. فعّل التحديث التلقائي أو أعد التشغيل عدة مرات.",
        "summary": "ملخص",
        "trend": "الاتجاه",
        "table": "جدول",
        "download_csv": "تنزيل CSV",
        "history_render_fail": "السجل موجود لكن تعذر عرضه كجدول في هذه البيئة.",
        "modeling_note": "**ملاحظة نمذجة:** يفرض هذا النموذج مخطط مقاطع قياسي ويُلحق المصدرية بكل تشغيل.",
        "data_sources_footer": "مصادر البيانات: TomTom Traffic Flow (v4) للمرور، وSviva لجودة الهواء، ومصادر حكومية لسعر الوقود. وتيرة التحديث ~5 دقائق. أعداد المركبات *مُقدّرة* من التدفق/السرعة وليست عدادًا رسميًا.",

        "loss_opt_per_hour": "لكل ساعة",
        "loss_opt_per_day": "لكل يوم",
        "loss_opt_per_year": "لكل سنة",
        "loss_opt_total_window": "الإجمالي (للنافذة)",
        "window_opt_1h": "آخر ساعة",
        "window_opt_24h": "آخر 24 ساعة",
        "window_opt_7d": "آخر 7 أيام",
        "window_opt_30d": "آخر 30 يومًا",
        "window_opt_all": "كل الوقت",
        "metric_vehicle_hours": "ساعات-مركبة",
        "metric_co2": "CO₂",
        "metric_excess_fuel": "وقود زائد",
        "metric_fuel_cost": "تكلفة الوقود",
        "trend_chart_caption": "دليل الألوان في الرسم: الأزرق = تكلفة الوقود (₪)، البرتقالي = CO₂ (كغ)، الأخضر = ساعات-مركبة (تأخير).",
        "series_fuel_cost": "تكلفة الوقود (₪)",
        "series_co2": "CO₂ (كغ)",
        "series_vehicle_hours": "ساعات-مركبة (تأخير)",

        "success_rate": "نسبة النجاح",
        "cache_hit_ratio": "نسبة إصابات التخزين المؤقت",
        "errors_session": "الأخطاء (الجلسة)",

        "download_xlsx": "تنزيل Excel",
        "export_note": "يتضمن التصدير الجدول والرسوم (مجمّعة حسب نفس النافذة/المقياس).",
        "time_value_caption": "تقدير خسارة قيمة الوقت (₪): ₪ {value:,.0f} (بافتراض ₪{rate:.2f}/ساعة-مركبة)",
        "extrapolated_caption": "تمت الاستقراء من {window}. المدة المُلاحظة: {hours:.2f} ساعة.",

        "official_card_title": "مرجع رسمي — للسياق فقط",
        "official_card_subtitle_context_only": "للإحاطة فقط: رقم رسمي مُقتبس للسياق وليس للتحقق من ""مصدر الحقيقة"".",
        "official_not_configured": "مصدر PDF رسمي مُوصى به (للسياق فقط) من أرشيف مراقب الدولة: تقرير مراقب الدولة — Abstracts\nhttps://library.mevaker.gov.il/sites/DigitalLibrary/Documents/2024/2024.11-75A-PartB/EN/2024.11-75A-PartB-All-Abstracts-EN.pdf\nاستخدم هذا الرابط كـ OFFICIAL_REPORT_URL واضبط OFFICIAL_SOURCE_LABEL / OFFICIAL_REPORT_YEAR / OFFICIAL_METRIC_LABEL / OFFICIAL_VALUE / OFFICIAL_UNIT (مثل ILS_per_year).",
        "official_source_label": "المصدر",
        "official_report_year": "سنة التقرير",
        "official_value_year": "سنة التقدير",
        "official_metric_label": "المقياس",
        "official_value_label": "القيمة",
        "official_unit_ils_per_year": "شيكل/سنة",
        "official_metric_state_comptroller_congestion_cost": "تقدير التكلفة الاقتصادية السنوية للازدحام المروري",
        "official_disclaimer_not_comparable": "عادةً لا توفر المصادر الحكومية العامة نظيرًا مباشرًا لعداد حيّ على مستوى ممر (vehicle-hours). لذلك يُعرض هذا المرجع الرسمي كقيمة سنوية/مجموعة للسياق فقط.",
        "official_disclaimer_planning_basis": "غياب نظير عام مباشر لا يعني غياب أدوات التخطيط: يعتمد التخطيط المروري غالبًا على نماذج مجمعة، واستبيانات، وبيانات حساسات/مشغلين، وتقييمات اقتصادية، لكن ما يُنشر للعامة يكون عادةً مؤشرات سنوية/مجمعة وليس عدادًا حيًا حسب الممر.",
    },
    "ru": {
        "app_title": "Ayalon — монитор физического воздействия",
        "app_subtitle": "**Версия:** 1.0 (Freeze) | **Слой:** L5 — Транспорт / Физическая истина | **Область:** трасса 20 (Аялон), Израиль",
        "language_label": "Язык",
        "sidebar_data_refresh": "Данные и обновление",
        "auto_refresh": "Автообновление каждые 5 минут",
        "loss_display_header": "Отображение потерь",
        "loss_display_label": "Показывать потери как",
        "history_window_label": "Окно истории",
        "system_health": "Состояние системы",
        "traffic_mode": "Режим трафика",
        "traffic_mode_help": "Выбери источник данных о трафике: реальные данные (TomTom) или демо‑данные (Sample) для просмотра.",
        "traffic_mode_opt_flow": "Реальные (TomTom)",
        "traffic_mode_opt_sample": "Демо (Sample)",
        "tab_dashboard": "Дашборд",
        "tab_history": "История и статистика",
        "tab_sources": "Источники и здоровье",

        "input_sources_header": "Источники входных данных",
        "system_header": "Система",
        "traffic_source": "Источник трафика",
        "air_quality_source": "Источник качества воздуха",
        "fuel_price_source": "Источник цены топлива",
        "updated": "Обновлено",
        "price_ils_per_l": "Цена (₪/л)",
        "traffic_age": "Возраст данных трафика",
        "no_segments": "Нет доступных сегментов трафика; проверь настройки или сеть",
        "losses_explained": "Потери — объяснение",
        "what_mean": "Что означают эти числа (простыми словами)",
        "what_mean_body": "- Vehicle-Hours (delay): суммарное дополнительное время всех машин из‑за пробок относительно свободного потока.\n- Excess fuel (L): лишнее топливо, сожжённое во время задержки (холостой ход/старт‑стоп).\n- CO₂ (kg): выбросы от этого лишнего топлива (2.31 кг CO₂ на литр).\n- Direct fuel cost (₪): лишнее топливо, умноженное на текущую цену топлива.\nЭто системные счётчики: они описывают общий эффект, а не одного водителя.",
        "provenance": "Происхождение данных (Provenance)",
        "model_version": "Версия модели",
        "constants_version": "Версия констант",
        "data_timestamp": "Метка времени данных",
        "pipeline_run_id": "ID прогона",
        "stale_warning": "Данные трафика УСТАРЕЛИ (старше чем 2×период)",
        "waiting_inputs": "Ожидание корректной цены топлива или трафика. Можно задать FUEL_PRICE_ILS как запасной вариант.",
        "history_header": "История и статистика",
        "history_caption": "Сохраняется локально во время мониторинга (SQLite).",
        "no_history": "Истории пока нет. Включи автообновление или запусти несколько раз.",
        "summary": "Сводка",
        "trend": "Тренд",
        "table": "Таблица",
        "download_csv": "Скачать CSV",
        "history_render_fail": "История есть, но её нельзя отрисовать таблицей в этой среде.",
        "modeling_note": "**Примечание по модели:** приложение приводит сегменты к канонической схеме и прикрепляет provenance к каждому прогону.",
        "data_sources_footer": "Источники данных: TomTom Traffic Flow (v4) для трафика, Sviva для воздуха и государственные источники для цены топлива. Период обновления ~5 минут (TTL кэша). Кол-во машин *оценивается* по потоку/скорости и не является официальным счётчиком.",

        "loss_opt_per_hour": "В час",
        "loss_opt_per_day": "В день",
        "loss_opt_per_year": "В год",
        "loss_opt_total_window": "Итого (окно)",
        "window_opt_1h": "Последний час",
        "window_opt_24h": "Последние 24 часа",
        "window_opt_7d": "Последние 7 дней",
        "window_opt_30d": "Последние 30 дней",
        "window_opt_all": "За всё время",
        "metric_vehicle_hours": "Машино‑часы",
        "metric_co2": "CO₂",
        "metric_excess_fuel": "Лишнее топливо",
        "metric_fuel_cost": "Стоимость топлива",
        "trend_chart_caption": "Легенда по цветам: синий = стоимость топлива (₪), оранжевый = CO₂ (кг), зелёный = машино‑часы (задержка).",
        "series_fuel_cost": "Стоимость топлива (₪)",
        "series_co2": "CO₂ (кг)",
        "series_vehicle_hours": "Машино‑часы (задержка)",

        "success_rate": "Успешные запросы",
        "cache_hit_ratio": "Попадания в кэш",
        "errors_session": "Ошибки (сессия)",

        "download_xlsx": "Скачать Excel",
        "export_note": "Экспорт включает таблицу и графики (агрегировано по тому же окну/масштабу).",
        "time_value_caption": "Оценка потерь времени (₪): ₪ {value:,.0f} (предположено ₪{rate:.2f}/машино‑час)",
        "extrapolated_caption": "Экстраполировано по окну: {window}. Наблюдаемая длительность: {hours:.2f} ч.",

        "official_card_title": "Официальный ориентир — только контекст",
        "official_card_subtitle_context_only": "Reference-only: цитируемая официальная оценка для контекста, не валидатор ""источника истины"".",
        "official_not_configured": "Вот официальный PDF-источник (reference-only) из архива מבקר המדינה: דו\"ח מבקר המדינה — Abstracts\nhttps://library.mevaker.gov.il/sites/DigitalLibrary/Documents/2024/2024.11-75A-PartB/EN/2024.11-75A-PartB-All-Abstracts-EN.pdf\nИспользуй этот URL как OFFICIAL_REPORT_URL и задай OFFICIAL_SOURCE_LABEL / OFFICIAL_REPORT_YEAR / OFFICIAL_METRIC_LABEL / OFFICIAL_VALUE / OFFICIAL_UNIT (например ILS_per_year).",
        "official_source_label": "Источник",
        "official_report_year": "Год отчёта",
        "official_value_year": "Год оценки",
        "official_metric_label": "Метрика",
        "official_value_label": "Значение",
        "official_unit_ils_per_year": "₪ в год",
        "official_metric_state_comptroller_congestion_cost": "Оценка годового экономического ущерба от дорожных заторов",
        "official_disclaimer_not_comparable": "Публичные государственные источники, как правило, не предоставляют прямого аналога live-счётчику vehicle-hours по конкретному коридору; поэтому официальный ориентир показан только как годовой/агрегированный контекст.",
        "official_disclaimer_planning_basis": "Отсутствие публичного прямого аналога не означает отсутствие моделей у государства: транспортное планирование обычно опирается на агрегированные модели, обследования, данные датчиков/операторов и экономические оценки, но в публичных публикациях это чаще годовые/агрегированные индикаторы, а не live-счётчик по коридору.",
    },
}


def _chart_bucket_for_loss_display(loss_display: str) -> str | None:
    if loss_display == "per_hour":
        return "1H"
    if loss_display == "per_day":
        return "1D"
    if loss_display == "per_year":
        return "1Y"
    return None


def _df_to_excel_bytes(df, *, bucket: str | None) -> bytes:
    import pandas as pd  # type: ignore
    from io import BytesIO

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="history", index=False)

        try:
            if bucket and 'recorded_at_utc' in df.columns:
                d = df.copy()
                d['recorded_at_utc'] = pd.to_datetime(d['recorded_at_utc'], errors='coerce', utc=True)
                d = d.dropna(subset=['recorded_at_utc'])
                if not d.empty:
                    d = d.sort_values('recorded_at_utc')
                    d = d.set_index('recorded_at_utc')
                    cols = [c for c in ['leakage_ils', 'co2_emissions_kg', 'delta_T_total_h'] if c in d.columns]
                    if cols:
                        trend = d[cols].resample(bucket).sum(min_count=1).dropna(how='all').reset_index()
                        trend.to_excel(writer, sheet_name="trend", index=False)
        except Exception:
            # Excel export must never fail.
            pass

    return buf.getvalue()


def _render_trend_chart(df, lang: str, *, bucket: str | None = None):
    """Render a stable, localized trend chart with an explicit color legend."""
    try:
        import pandas as pd  # type: ignore
        import altair as alt  # type: ignore

        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return

        d = df.copy()
        d['recorded_at_utc'] = pd.to_datetime(d['recorded_at_utc'], errors='coerce', utc=True)
        d = d.dropna(subset=['recorded_at_utc'])
        d = d.sort_values('recorded_at_utc')
        cols = ['recorded_at_utc', 'leakage_ils', 'co2_emissions_kg', 'delta_T_total_h']
        existing = [c for c in cols if c in d.columns]
        if 'recorded_at_utc' not in existing:
            return
        d = d[existing]

        if bucket:
            d = d.set_index('recorded_at_utc')
            d = d.resample(bucket).sum(min_count=1)
            d = d.reset_index()

        d = d.dropna(how='all', subset=[c for c in existing if c != 'recorded_at_utc'])
        if d.empty:
            return

        series = [
            ('leakage_ils', _t('series_fuel_cost', lang), '#1f77b4'),
            ('co2_emissions_kg', _t('series_co2', lang), '#ff7f0e'),
            ('delta_T_total_h', _t('series_vehicle_hours', lang), '#2ca02c'),
        ]

        rows = []
        for col, label, color in series:
            if col not in d.columns:
                continue
            tmp = d[['recorded_at_utc', col]].rename(columns={col: 'value'})
            tmp['metric'] = label
            tmp['color'] = color
            rows.append(tmp)
        if not rows:
            return
        long_df = pd.concat(rows, ignore_index=True)

        chart = (
            alt.Chart(long_df)
            .mark_line()
            .encode(
                x=alt.X('recorded_at_utc:T', title=None),
                y=alt.Y('value:Q', title=None),
                color=alt.Color('metric:N',
                                scale=alt.Scale(domain=[s[1] for s in series], range=[s[2] for s in series]),
                                legend=alt.Legend(title=None)),
                tooltip=[
                    alt.Tooltip('recorded_at_utc:T', title='time'),
                    alt.Tooltip('metric:N', title=_t('trend', lang)),
                    alt.Tooltip('value:Q', title='value'),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption(_t('trend_chart_caption', lang))
    except Exception:
        # Never break UI on chart rendering.
        return


def _t(key: str, lang: str) -> str:
    table = _I18N.get((lang or "en").lower(), _I18N["en"])
    return str(table.get(key, _I18N["en"].get(key, key)))


def _maybe_translate(label_or_key: str | None, lang: str) -> str:
    if not label_or_key:
        return ""
    s = str(label_or_key)
    table = _I18N.get((lang or "en").lower(), _I18N["en"])
    if s in table or s in _I18N.get("en", {}):
        return _t(s, lang)
    return s


def _format_int_grouped(n: float, sep: str = ",") -> str:
    try:
        i = int(round(float(n)))
    except Exception:
        return str(n)
    s = f"{i:,}"
    if sep != ",":
        s = s.replace(",", sep)
    return s


def _format_ils_amount(value: float, lang: str) -> str:
    # Keep it simple & consistent: Hebrew/English/Arabic use commas, Russian uses spaces.
    sep = " " if (lang or "").lower() == "ru" else ","
    return f"₪ {_format_int_grouped(value, sep=sep)}"


# Language selector (above Data & Refresh)
default_lang_display = LANG_CHOICES[0][0]  # Hebrew
lang_display = st.sidebar.selectbox(
    _t("language_label", "he") + " / " + _t("language_label", "en"),
    options=[d for d, _c in LANG_CHOICES],
    index=0,
    key="lang_display",
)
lang = _lang_display_to_code.get(lang_display, "he")

# RTL/LTR direction
if lang in ("he", "ar"):
    st.markdown(
        """
        <style>
        .stApp { direction: rtl; }
        .stSidebar { direction: rtl; }
        .stMarkdown, .stText, .stCaption { text-align: right; }
        [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"] { text-align: right; }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
        .stApp { direction: ltr; }
        .stSidebar { direction: ltr; }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.title(_t("app_title", lang))
st.markdown(_t("app_subtitle", lang))

model = AyalonModel()
history = HistoryStore()


def _parse_iso_to_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _fetch_with_retries(label: str, fn, retries: int = 2, base_delay_s: float = 0.8):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn(), None
        except Exception as e:
            last_exc = e
            msg = str(e)
            # If rate-limited, don't hammer.
            if "rate-limited" in msg.lower() or "retry_after" in msg.lower():
                break
            if attempt < retries:
                time.sleep(base_delay_s * (2 ** attempt))
    return None, last_exc


def _history_window_seconds(choice: str) -> int | None:
    mapping = {
        "1h": 3600,
        "24h": 24 * 3600,
        "7d": 7 * 24 * 3600,
        "30d": 30 * 24 * 3600,
        "all": None,
    }
    return mapping.get(choice)


def _compute_aggregates_from_history(df, window_s: int | None):
    """Return (df_window, totals_dict, duration_hours) using recorded_at_utc."""
    import pandas as pd  # type: ignore

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None, {}, 0.0

    d = df.copy()
    d['recorded_at_utc'] = pd.to_datetime(d['recorded_at_utc'], errors='coerce', utc=True)
    d = d.dropna(subset=['recorded_at_utc'])
    if d.empty:
        return None, {}, 0.0

    now = pd.Timestamp.utcnow()
    # pandas versions differ: Timestamp.utcnow() may be tz-aware already.
    if getattr(now, 'tzinfo', None) is None:
        now = now.tz_localize('UTC')
    else:
        now = now.tz_convert('UTC')
    if window_s is not None:
        start = now - pd.Timedelta(seconds=int(window_s))
        d = d[d['recorded_at_utc'] >= start]
        if d.empty:
            return None, {}, 0.0

    d = d.sort_values('recorded_at_utc')
    duration_h = (d['recorded_at_utc'].max() - d['recorded_at_utc'].min()).total_seconds() / 3600.0
    duration_h = max(duration_h, 1e-6)

    def total(col: str) -> float:
        if col not in d.columns:
            return 0.0
        s = pd.to_numeric(d[col], errors='coerce').dropna()
        return float(s.sum()) if not s.empty else 0.0

    totals = {
        'delta_T_total_h': total('delta_T_total_h'),
        'fuel_excess_L': total('fuel_excess_L'),
        'co2_emissions_kg': total('co2_emissions_kg'),
        'leakage_ils': total('leakage_ils'),
    }
    return d, totals, duration_h

# Controls
st.sidebar.header(_t("sidebar_data_refresh", lang))

st.sidebar.subheader(_t("loss_display_header", lang))
_loss_opts = [
    ("loss_opt_per_hour", "per_hour"),
    ("loss_opt_per_day", "per_day"),
    ("loss_opt_per_year", "per_year"),
    ("loss_opt_total_window", "total_window"),
]
loss_display_label = st.sidebar.selectbox(
    _t("loss_display_label", lang),
    options=[_t(k, lang) for k, _code in _loss_opts],
    index=1,
)
loss_display = dict(((_t(k, lang)), code) for k, code in _loss_opts).get(loss_display_label, "per_day")

_window_opts = [
    ("window_opt_1h", "1h"),
    ("window_opt_24h", "24h"),
    ("window_opt_7d", "7d"),
    ("window_opt_30d", "30d"),
    ("window_opt_all", "all"),
]
history_window_label = st.sidebar.selectbox(
    _t("history_window_label", lang),
    options=[_t(k, lang) for k, _code in _window_opts],
    index=1,
)
history_window_choice = dict(((_t(k, lang)), code) for k, code in _window_opts).get(history_window_label, "24h")

# Public-friendly system status (no secrets, no external API calls)
_sys_status = get_quick_status()
st.sidebar.info(f"{_t('system_health', lang)}: {_sys_status}")

# Lightweight analytics summary
summary = get_dashboard_summary()
st.sidebar.metric(_t("success_rate", lang), summary.get("success_rate", "n/a"))
st.sidebar.metric(_t("cache_hit_ratio", lang), summary.get("cache_hit_ratio", "n/a"))
st.sidebar.write(f"{_t('errors_session', lang)}: {summary.get('errors_this_session', 0)}")

# ── Data acquisition ───────────────────────────────────────────────────
# readonly (default): read latest run from SQLite only — zero API calls.
# live (AYALON_UI_MODE=live): old behaviour — fetch TomTom, run model, persist.

def _acquire_live():
    """Legacy live-fetch path (used only when AYALON_UI_MODE=live)."""
    api_key = SecureConfig.get_tomtom_api_key()
    default_sample = api_key is None and SecureConfig.get_enable_sample_mode()
    traffic_mode = "sample" if default_sample else "flow"

    tomtom_data, tomtom_exc = _fetch_with_retries(
        "tomtom",
        lambda: tomtom.get_ayalon_segments(api_key, cache_ttl_s=SecureConfig.get_cache_ttl(), mode=traffic_mode),
        retries=2,
    )
    if tomtom_data is None:
        cached = tomtom.get_cached_ayalon_segments(mode=traffic_mode, max_age_s=24 * 3600)
        if cached:
            cached = dict(cached)
            cached["errors"] = ["Using cached traffic due to live fetch failure"]
            tomtom_data = cached
        else:
            api_err = ErrorHandler.handle_api_call_error(tomtom_exc, service="tomtom") if tomtom_exc else ErrorHandler.handle_api_call_error(RuntimeError("TomTom fetch failed"), service="tomtom")
            tomtom_data = {"source_id": "tomtom:error", "segments": [], "errors": [api_err.message], "fetched_at": datetime.utcnow().isoformat() + "Z"}
        record_request(success=False, error_code="tomtom_fallback")
    else:
        if tomtom_data.get("errors"):
            record_request(success=False, error_code=str(tomtom_data["errors"][0])[:60])
        else:
            record_request(success=True)

    aq_data, aq_exc = _fetch_with_retries("air_quality", lambda: get_air_quality_for_ayalon(cache_ttl_s=600), retries=1)
    if aq_data is None or aq_data.get("error"):
        cached_aq = get_cached_air_quality(max_age_s=24 * 3600)
        if cached_aq:
            aq_data = dict(cached_aq)
            aq_data["error"] = aq_data.get("error") or "Using cached air quality due to live fetch failure"
        elif aq_data is None:
            aq_data = {"source_id": "air-quality:error", "fetched_at": None, "metrics": {}, "error": str(aq_exc) if aq_exc else "Air quality fetch failed"}

    fuel_data, fuel_exc = _fetch_with_retries("fuel", lambda: fetch_current_fuel_price(), retries=1, base_delay_s=1.2)
    if fuel_data is None:
        cached_fuel = get_cached_fuel_price(max_age_s=14 * 86400)
        if cached_fuel:
            fuel_data = dict(cached_fuel)
            fuel_data["source_id"] = str(fuel_data.get("source_id", "fuel")) + ":cached"
        else:
            fuel_data = {"source_id": "fuel:error", "price_ils_per_l": None}

    vehicle_count_mode = tomtom_data.get('vehicle_count_mode')
    segments = tomtom_data.get('segments', [])

    results = None
    if segments and fuel_data.get('price_ils_per_l') is not None:
        _model = AyalonModel()
        src_ids = {
            'traffic': tomtom_data.get('source_id'),
            'air': aq_data.get('source_id'),
            'fuel': fuel_data.get('source_id'),
        }
        data_ts = tomtom_data.get('fetched_at')
        p_fuel = float(fuel_data['price_ils_per_l'])
        results = _model.run_model(segments, data_timestamp_utc=data_ts, source_ids=src_ids, p_fuel_ils_per_l=p_fuel, vehicle_count_mode=vehicle_count_mode)
        now_ts = time.time()
        tomtom_ts = _parse_iso_to_ts(tomtom_data.get('fetched_at', '1970-01-01T00:00:00Z'))
        tomtom_age = now_ts - tomtom_ts
        try:
            history.record_run(results=results, tomtom_data=tomtom_data, aq_data=aq_data, fuel_data=fuel_data, tomtom_age_s=tomtom_age)
        except Exception:
            pass

    return results, vehicle_count_mode, tomtom_data, aq_data, fuel_data


def _acquire_readonly():
    """Read latest collector run from SQLite — zero API calls.

    Uses fetch_latest_traffic_run() which filters for rows with a valid
    traffic_source_id, ensuring fuel-only rows cannot confuse the display.
    """
    latest = history.fetch_latest_traffic_run()
    if latest is None:
        # Fall back to any run at all (covers first-use / sample-only DBs)
        latest = history.fetch_latest_run()
    if latest is None:
        return None, None, None, None, None

    results = {
        'delta_T_total_h': latest.get('delta_T_total_h'),
        'fuel_excess_L': latest.get('fuel_excess_L'),
        'leakage_ils': latest.get('leakage_ils'),
        'co2_emissions_kg': latest.get('co2_emissions_kg'),
        'model_version': '1.0-freeze',
        'constants_version': 'AppendixA-v1.2',
        'data_timestamp_utc': latest.get('data_timestamp_utc'),
        'data_source_ids': {
            'traffic': latest.get('traffic_source_id'),
            'air': latest.get('air_source_id'),
            'fuel': latest.get('fuel_source_id'),
        },
        'pipeline_run_id': latest.get('pipeline_run_id'),
        'vehicle_count_mode': latest.get('vehicle_count_mode'),
    }
    vehicle_count_mode = latest.get('vehicle_count_mode')

    tomtom_data = {
        'source_id': latest.get('traffic_source_id') or 'sqlite:readonly',
        'fetched_at': latest.get('tomtom_fetched_at'),
        'segments': [],   # not needed for display — metrics already computed
        'vehicle_count_mode': vehicle_count_mode,
    }
    aq_data = {
        'source_id': latest.get('air_source_id') or 'sqlite:readonly',
        'fetched_at': latest.get('air_fetched_at'),
        'metrics': {},
    }
    fuel_data = {
        'source_id': latest.get('fuel_source_id') or 'sqlite:readonly',
        'fetched_at': latest.get('fuel_fetched_at'),
    }

    return results, vehicle_count_mode, tomtom_data, aq_data, fuel_data


if _UI_MODE == "live":
    st.sidebar.warning("⚠ UI mode: **live** (TomTom API calls enabled)")
    results, vehicle_count_mode, tomtom_data, aq_data, fuel_data = _acquire_live()
else:
    results, vehicle_count_mode, tomtom_data, aq_data, fuel_data = _acquire_readonly()

tab_dashboard, tab_history, tab_sources = st.tabs([
    _t("tab_dashboard", lang),
    _t("tab_history", lang),
    _t("tab_sources", lang),
])

with tab_sources:
    st.header(_t("input_sources_header", lang))
    col1, col2, col3 = st.columns(3)
    if tomtom_data:
        col1.metric(_t("traffic_source", lang), tomtom_data.get('source_id', 'tomtom:unknown'))
        col1.write(f"{_t('updated', lang)}: {tomtom_data.get('fetched_at')}")
        if tomtom_data.get('errors'):
            col1.warning(str(tomtom_data.get('errors')[0])[:200])
    else:
        col1.metric(_t("traffic_source", lang), "n/a")

    if aq_data:
        col2.metric(_t("air_quality_source", lang), aq_data.get('source_id', 'air:unknown'))
        col2.write(f"{_t('updated', lang)}: {aq_data.get('fetched_at')}")
        aq_metrics = aq_data.get('metrics') or {}
        if aq_metrics.get('pm2_5_ug_m3') is not None:
            col2.write(f"PM2.5 (µg/m³): {aq_metrics.get('pm2_5_ug_m3')}")
        if aq_metrics.get('us_aqi') is not None:
            col2.write(f"US AQI: {aq_metrics.get('us_aqi')}")
        if aq_data.get('error'):
            col2.warning(str(aq_data.get('error'))[:200])
    else:
        col2.metric(_t("air_quality_source", lang), "n/a")

    if fuel_data:
        fuel_sid = fuel_data.get('source_id', 'gov-or-env')
        col3.metric(_t("fuel_price_source", lang), fuel_sid)
        col3.write(f"{_t('price_ils_per_l', lang)}: {fuel_data.get('price_ils_per_l', 'n/a')}")
        # Show adapter provenance detail (from collector-written data)
        fuel_raw = fuel_data.get('raw') or {}
        adapter_name = fuel_raw.get('adapter', '')
        if adapter_name == 'ckan_datastore':
            col3.caption(f"Wholesale: {fuel_raw.get('wholesale_per_l', '?')} ₪/L + Excise: {fuel_raw.get('excise_per_l', '?')} ₪/L + Margin: {fuel_raw.get('retail_margin_ils', '?')} ₪/L × (1+VAT)")
        elif adapter_name == 'pdf_notice':
            col3.caption(f"Parsed from: {fuel_raw.get('notice_pdf_url', 'PDF')}")
        elif adapter_name == 'env_override':
            col3.caption("⚠ Manual env override (FUEL_PRICE_ILS)")
        if ':cached' in str(fuel_sid):
            col3.warning("Using stale cached fuel price")
    else:
        col3.metric(_t("fuel_price_source", lang), "n/a")

    st.subheader(_t("system_header", lang))
    _src_status = get_quick_status()
    st.info(f"{_t('system_health', lang)}: {_src_status}")

banner = normalization_banner_text(vehicle_count_mode, lang=lang)
if banner:
    st.info(banner)

if results is not None:
    with tab_dashboard:
        st.header(_t("losses_explained", lang))
        delta_T = float(results['delta_T_total_h'])
        time_value_ils = delta_T * float(getattr(model, 'Value_of_Time_ILS_per_h', 62.5))
        # Use monitoring history to scale numbers for non-technical users (per hour/day/year/total)
        totals = None
        duration_h = 0.0
        try:
            import pandas as pd  # type: ignore

            df_hist = history.fetch_runs_df(limit=5000)
            window_s = _history_window_seconds(history_window_choice)
            _dfw, totals, duration_h = _compute_aggregates_from_history(df_hist, window_s)
        except Exception:
            totals = None

        def scale(total_value: float) -> float:
            if loss_display == "total_window":
                return float(total_value)
            rate_per_h = float(total_value) / float(duration_h or 1e-6)
            if loss_display == "per_hour":
                return rate_per_h
            if loss_display == "per_day":
                return rate_per_h * 24.0
            if loss_display == "per_year":
                return rate_per_h * 24.0 * 365.0
            return float(total_value)

        use_history = isinstance(totals, dict) and bool(totals)
        colA, colB, colC, colD = st.columns(4)
        if use_history:
            colA.metric(_t("metric_vehicle_hours", lang), f"{scale(totals.get('delta_T_total_h', 0.0)):,.2f} h")
            colB.metric(_t("metric_co2", lang), f"{scale(totals.get('co2_emissions_kg', 0.0)):,.2f} kg")
            colC.metric(_t("metric_excess_fuel", lang), f"{scale(totals.get('fuel_excess_L', 0.0)):,.2f} L")
            colD.metric(_t("metric_fuel_cost", lang), f"₪ {scale(totals.get('leakage_ils', 0.0)):,.2f}")
            if loss_display != "total_window":
                st.caption(_t("extrapolated_caption", lang).format(window=history_window_label, hours=duration_h))
        else:
            colA.metric(_t("metric_vehicle_hours", lang), f"{delta_T:,.2f} h")
            colB.metric(_t("metric_co2", lang), f"{results['co2_emissions_kg']:,.2f} kg")
            colC.metric(_t("metric_excess_fuel", lang), f"{results['fuel_excess_L']:,.2f} L")
            colD.metric(_t("metric_fuel_cost", lang), f"₪ {results['leakage_ils']:,.2f}")

        st.caption(
            _t("time_value_caption", lang).format(
                value=float(time_value_ils),
                rate=float(getattr(model, 'Value_of_Time_ILS_per_h', 62.5)),
            )
        )

        with st.expander(_t("what_mean", lang), expanded=True):
            st.write(_t("what_mean_body", lang))

        st.subheader(_t("provenance", lang))
        st.write(f"{_t('model_version', lang)}: {results['model_version']}")
        st.write(f"{_t('constants_version', lang)}: {results['constants_version']}")
        st.write(f"{_t('data_timestamp', lang)}: {results['data_timestamp_utc']}")
        st.write(f"{_t('pipeline_run_id', lang)}: {results['pipeline_run_id']}")

        stale = False
        _health = compute_traffic_health()
        _health_status = _health.get("status", "unknown")
        if _health_status in ("stale", "collector_down"):
            stale = True
        if stale:
            _stale_msg = _t("stale_warning", lang)
            _age = _health.get("age_s")
            if _age is not None:
                _stale_msg += f"  ({int(_age)}s)"
            if _health_status == "collector_down":
                _stale_msg += "  [collector may be down]"
            st.warning(_stale_msg)
            record_stale_data()

        # Mini trend chart (last N runs)
        df = history.fetch_runs_df(limit=300)
        _render_trend_chart(df, lang, bucket=_chart_bucket_for_loss_display(loss_display))
else:
    with tab_dashboard:
        st.info(_t("waiting_inputs", lang))


with tab_history:
    st.header(_t("history_header", lang))
    st.caption(_t("history_caption", lang))

    df = history.fetch_runs_df(limit=5000)
    try:
        import pandas as pd  # type: ignore
    except Exception:
        pd = None  # type: ignore

    if pd is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.info(_t("no_history", lang))
    else:
        # Compute window aggregates (never fail the entire tab)
        window_s = _history_window_seconds(history_window_choice)
        dfw, totals, duration_h = _compute_aggregates_from_history(df, window_s)

        # Latest first for table readability
        df_table = df.copy().sort_values('recorded_at_utc', ascending=False)

        # Summary
        st.subheader(_t("summary", lang))
        total_leak_all = float(df_table['leakage_ils'].dropna().sum()) if 'leakage_ils' in df_table else 0.0
        total_co2_all = float(df_table['co2_emissions_kg'].dropna().sum()) if 'co2_emissions_kg' in df_table else 0.0
        avg_leak_all = float(df_table['leakage_ils'].dropna().mean()) if 'leakage_ils' in df_table and df_table['leakage_ils'].notna().any() else 0.0

        # Window-based scaling
        window_leak = float((totals or {}).get('leakage_ils', 0.0))
        window_co2 = float((totals or {}).get('co2_emissions_kg', 0.0))
        window_delay_h = float((totals or {}).get('delta_T_total_h', 0.0))
        rate_per_h = (window_leak / duration_h) if duration_h else 0.0
        leak_per_day = rate_per_h * 24.0
        leak_per_year = rate_per_h * 24.0 * 365.0

        c1, c2, c3 = st.columns(3)
        c1.metric(f"{_t('metric_fuel_cost', lang)} (all time, ₪)", f"₪ {total_leak_all:,.0f}")
        c2.metric(f"{_t('metric_co2', lang)} (all time, kg)", f"{total_co2_all:,.0f}")
        c3.metric(f"{_t('metric_fuel_cost', lang)} / run (all time, ₪)", f"₪ {avg_leak_all:,.0f}")

        st.caption(f"{_t('history_window_label', lang)}: {history_window_label} | {duration_h:.2f} h")
        w1, w2, w3, w4 = st.columns(4)
        w1.metric(f"{_t('metric_fuel_cost', lang)} ({_t('loss_opt_total_window', lang)}, ₪)", f"₪ {window_leak:,.0f}")
        w2.metric(f"{_t('metric_fuel_cost', lang)} ({_t('loss_opt_per_hour', lang)}, ₪/h)", f"₪ {rate_per_h:,.0f}")
        w3.metric(f"{_t('metric_fuel_cost', lang)} ({_t('loss_opt_per_day', lang)}, ₪/day)", f"₪ {leak_per_day:,.0f}")
        w4.metric(f"{_t('metric_fuel_cost', lang)} ({_t('loss_opt_per_year', lang)}, ₪/yr)", f"₪ {leak_per_year:,.0f}")

        st.caption(f"delay={window_delay_h:,.1f} vehicle-hours, CO₂={window_co2:,.0f} kg")

        st.subheader(_t("official_card_title", lang))
        st.caption(_t("official_card_subtitle_context_only", lang))

        official = fetch_official_reference_card(cache_ttl_s=24 * 3600)
        if not bool(official.get("configured")):
            st.info(_t("official_not_configured", lang))
            if official.get("error"):
                st.caption(str(official.get("error"))[:200])
        else:
            src_label = str(official.get("source_label") or "")
            report_year = official.get("report_year")
            report_url = str(official.get("report_url") or "")
            metric_label_raw = str(official.get("metric_label") or "")
            metric_label = _maybe_translate(metric_label_raw, lang)
            unit = str(official.get("unit") or "")
            value = float(official.get("value") or 0.0)
            value_year = official.get("value_year")

            if unit == "ILS_per_year":
                formatted_value = _format_ils_amount(value, lang)
                unit_label = _t("official_unit_ils_per_year", lang)
                formatted_value = f"{formatted_value} / {unit_label}"
            else:
                formatted_value = f"{value:,.0f} {unit}".strip()

            left, right = st.columns([2, 1])
            with left:
                if src_label:
                    st.caption(f"{_t('official_source_label', lang)}: {src_label}")
                if report_year is not None:
                    st.caption(f"{_t('official_report_year', lang)}: {report_year}")
                if value_year is not None and str(value_year) != str(report_year):
                    st.caption(f"{_t('official_value_year', lang)}: {value_year}")
                if report_url:
                    st.markdown(f"[{report_url}]({report_url})")
                if metric_label:
                    st.caption(f"{_t('official_metric_label', lang)}: {metric_label}")

            with right:
                st.metric(_t("official_value_label", lang), formatted_value)

        st.markdown(_t("official_disclaimer_not_comparable", lang))
        st.markdown(_t("official_disclaimer_planning_basis", lang))

        # Trend chart (bucketed by selected loss display)
        st.subheader(_t("trend", lang))
        _render_trend_chart(df, lang, bucket=_chart_bucket_for_loss_display(loss_display))

        # Table + downloads
        st.subheader(_t("table", lang))
        cols = [
            'recorded_at_utc',
            'data_timestamp_utc',
            'delta_T_total_h',
            'fuel_excess_L',
            'co2_emissions_kg',
            'leakage_ils',
            'traffic_source_id',
            'air_source_id',
            'fuel_source_id',
            'vehicle_count_mode',
            'tomtom_age_s',
        ]
        existing = [c for c in cols if c in df_table.columns]

        try:
            st.dataframe(df_table[existing], use_container_width=True)
        except Exception:
            st.warning(_t("history_render_fail", lang))

        csv = df_table[existing].to_csv(index=False)
        export_bucket = _chart_bucket_for_loss_display(loss_display)
        xlsx_bytes = _df_to_excel_bytes(df_table[existing], bucket=export_bucket)

        b1, b2 = st.columns(2)
        b1.download_button(_t("download_csv", lang), data=csv, file_name="monitor_history.csv", mime="text/csv")
        b2.download_button(_t("download_xlsx", lang), data=xlsx_bytes, file_name="monitor_history.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption(_t("export_note", lang))

st.markdown("---")
st.markdown(_t("modeling_note", lang))
st.caption(
    _t("data_sources_footer", lang)
)