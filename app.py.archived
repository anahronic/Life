import streamlit as st
from datetime import date
from pyluach import dates
from pyluach.dates import gematria

letter_to_value = {v: k for k, v in gematria._GEMATRIOS.items()}

def from_hebrew_number_year(s):
    s_clean = s.replace('״', '').replace('׳', '')
    value = 0
    for char in s_clean:
        if char in letter_to_value:
            value += letter_to_value[char]
    value += 5000  # Always add 5000 for modern Hebrew years
    return value

def from_hebrew_number_day(s):
    s_clean = s.replace('״', '').replace('׳', '')
    value = 0
    for char in s_clean:
        if char in letter_to_value:
            value += letter_to_value[char]
    return value

# --- Логика DKP-0-TIME-001 ---
def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    if year < 0: year += 1
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return (day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045)

def jdn_to_gregorian(jdn: int, lang='EN') -> str:
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + (m // 10)
    
    suffixes = {
        "EN": "BC", "RU": "до н.э.", "HE": "לפנה״ס", "AR": "ق.м", "ZH": "公元前",
        "ES": "a.C.", "FR": "av. J.-C.", "DE": "v. Chr.", "IT": "a.C.", "PT": "a.C."
    }
    suffix = suffixes.get(lang, "BC")
    if year <= 0:
        return f"{abs(year - 1)} {suffix}-{month:02d}-{day:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def jdn_to_ymd(jdn: int) -> tuple:
    """Return (year, month, day) for a given JDN using the same algorithm as jdn_to_gregorian.

    Raises if year <= 0 (dates before year 1) which are not representable as datetime.date.
    """
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + (m // 10)
    if year <= 0:
        raise ValueError('Year <= 0 not supported for python date conversion')
    return year, month, day

def is_valid_greg(y, m, d):
    if y == 0 or not (-5000 <= y <= 5000): return False
    try:
        if y > 0: date(y, m, d)
        else:
            if not (1 <= m <= 12) or not (1 <= d <= 31): return False
        return True
    except: return False

# Получить текущую дату и вычислить соответствующие значения для дефолтов
today = date.today()
current_year = today.year
current_month = today.month
current_day = today.day
current_jdn = gregorian_to_jdn(current_year, current_month, current_day)
current_dy = current_jdn // 360
current_doy = (current_jdn % 360) + 1
try:
    current_heb = dates.HebrewDate.from_pydate(today)
    current_heb_year = current_heb.year
    current_heb_month = current_heb.month
    current_heb_day = current_heb.day
except:
    # Fallback на фиксированные значения, если ошибка
    current_heb_year = 5786
    current_heb_month = 5
    current_heb_day = 3

# --- Словари (10 языков) ---
LANGS = {
    'RU': ['Григ. ➔ DTI/Евр.', 'DTI ➔ Григ./Евр.', 'Евр. ➔ Григ./DTI', 'Год', 'Месяц', 'День', 'Ошибка: дата неверна', 'Тип ввода', 'Численный', 'Буквенный', 'Год (буквы)', 'День (буквы)', 'Евр.', 'Григорианский:', 'DTI', 'Модель Ayalon'],
    'EN': ['Greg ➔ DTI/Heb', 'DTI ➔ Greg/Heb', 'Heb ➔ Greg/DTI', 'Year', 'Month', 'Day', 'Error: Invalid Date', 'Input Type', 'Numeric', 'Letter', 'Year (letters)', 'Day (letters)', 'Heb', 'Gregorian:', 'DTI', 'Ayalon Model'],
    'HE': ['גרגוריאני ➔ DTI/עברי', 'DTI ➔ גרגוריאני/עברי', 'עברי ➔ גרגוריאני/DTI', 'שנה', 'חודש', 'יום', 'שגיאה: תאריך לא תקין', 'סוג קלט', 'מספרי', 'אותיות', 'שנה (אותיות)', 'יום (אותיות)', 'עברי', 'גרגוריאני:', 'DTI', 'מודל Ayalon'],
    'AR': ['ميلادي ➔ DTI/عبري', 'DTI ➔ ميلادي/عبري', 'عبري ➔ ميلادي/DTI', 'سنة', 'شهر', 'يوم', 'خطأ: تاريخ غير صحيح', 'نوع الإدخال', 'رقمي', 'حرفي', 'سنة (حروف)', 'يوم (حروف)', 'عبري', 'ميلادي:', 'DTI', 'نموذج Ayalon'],
    'ZH': ['公历 ➔ DTI/希伯来', 'DTI ➔ 公历/希伯来', '希伯来 ➔ 公历/DTI', '年', '月', '日', '错误：日期无效', '输入类型', '数字', '字母', '年（字母）', '日（字母）', '希伯来', '公历:', 'DTI', 'Ayalon 模型'],
    'ES': ['Greg ➔ DTI/Heb', 'DTI ➔ Greg/Heb', 'Heb ➔ Greg/DTI', 'Año', 'Mes', 'Día', 'Error: Fecha inválida', 'Tipo de entrada', 'Numérico', 'Letra', 'Año (letras)', 'Día (letras)', 'Heb', 'Gregoriano:', 'DTI', 'Modelo Ayalon'],
    'FR': ['Grég ➔ DTI/Heb', 'DTI ➔ Grég/Heb', 'Heb ➔ Grég/DTI', 'Année', 'Mois', 'Jour', 'Erreur: Date invalide', 'Type d\'entrée', 'Numérique', 'Lettre', 'Année (lettres)', 'Jour (lettres)', 'Heb', 'Grégorien:', 'DTI', 'Modèle Ayalon'],
    'DE': ['Greg ➔ DTI/Heb', 'DTI ➔ Greg/Heb', 'Heb ➔ Greg/DTI', 'Jahr', 'Monat', 'Tag', 'Fehler: Ungültiges Datum', 'Eingabetyp', 'Numerisch', 'Buchstabe', 'Jahr (Buchstaben)', 'Tag (Buchstaben)', 'Heb', 'Gregorianisch:', 'DTI', 'Ayalon Modell'],
    'IT': ['Greg ➔ DTI/Ebr', 'DTI ➔ Greg/Ebr', 'Ebr ➔ Greg/DTI', 'Anno', 'Mese', 'Giorno', 'Errore: Data non valida', 'Tipo di input', 'Numerico', 'Lettera', 'Anno (lettere)', 'Giorno (lettere)', 'Ebr', 'Gregoriano:', 'DTI', 'Modello Ayalon'],
    'PT': ['Greg ➔ DTI/Heb', 'DTI ➔ Greg/Heb', 'Heb ➔ Greg/DTI', 'Ano', 'Mês', 'Dia', 'Erro: Data inválida', 'Tipo de entrada', 'Numérico', 'Letra', 'Ano (letras)', 'Dia (letras)', 'Heb', 'Gregoriano:', 'DTI', 'Modelo Ayalon']
}

st.set_page_config(page_title="DTI Converter & Ayalon Model", layout="wide")
choice = st.sidebar.selectbox("Language", list(LANGS.keys()), index=1)
L = LANGS[choice]

# Создание вкладок
t1, t2, t3 = st.tabs([L[0], L[1], L[2]])

with t1:
    st.header(L[0])
    c1, c2, c3 = st.columns(3)
    y1 = c1.number_input(L[3], -5000, 5000, current_year, key="y1")
    m1 = c2.number_input(L[4], 1, 12, current_month, key="m1")
    d1 = c3.number_input(L[5], 1, 31, current_day, key="d1")
    if is_valid_greg(y1, m1, d1):
        j = gregorian_to_jdn(y1, m1, d1)
        st.metric(L[14], f"DY{j//360}-{(j%360)+1:03d}")
        try:
            yj, mj, dj = jdn_to_ymd(j)
            h = dates.HebrewDate.from_pydate(date(yj, mj, dj))
            st.success(f"{L[12]}: {h.year}-{h.month}-{h.day} ({h.hebrew_date_string()})")
        except: st.warning(L[6])
    else: st.error(L[6])

with t2:
    st.header(L[1])
    c_dy, c_doy = st.columns(2)
    dy2 = c_dy.number_input("DY", -10000, 10000, current_dy, key="dy2")
    doy2 = c_doy.number_input("DOY (1-360)", 1, 360, current_doy, key="doy2")
    j2 = dy2 * 360 + (doy2 - 1)
    st.subheader(f"{L[13]} {jdn_to_gregorian(j2, choice)}")
    try:
        yj2, mj2, dj2 = jdn_to_ymd(j2)
        h2 = dates.HebrewDate.from_pydate(date(yj2, mj2, dj2))
        st.subheader(f"{L[12]}: {h2.year}-{h2.month}-{h2.day} ({h2.hebrew_date_string()})")
    except: st.write(L[6])

with t3:
    st.header(L[2])
    input_type = st.radio(L[7], [L[8], L[9]], key="input_type")
    if input_type == L[8]:
        ch1, ch2, ch3 = st.columns(3)
        y3 = ch1.number_input(L[3], 1, 9999, current_heb_year, key="y3")
        m3 = ch2.number_input(L[4], 1, 13, current_heb_month, key="m3")
        d3 = ch3.number_input(L[5], 1, 31, current_heb_day, key="d3")
    else:
        months_hebrew = ['ניסן', 'אייר', 'סיון', 'תמוז', 'אב', 'אלול', 'תשרי', 'חשון', 'כסלו', 'טבת', 'שבט', 'אדר', 'אדר ב']
        month_dict = {name: i+1 for i, name in enumerate(months_hebrew)}
        ch1, ch2, ch3 = st.columns(3)
        year_text = ch1.text_input(L[10], key="y3_heb")
        month_name = ch2.selectbox(L[4], months_hebrew, key="m3_heb")
        day_text = ch3.text_input(L[11], key="d3_heb")
        try:
            y3 = from_hebrew_number_year(year_text)
            m3 = month_dict[month_name]
            d3 = from_hebrew_number_day(day_text)
        except:
            st.error(L[6])  # вместо "Неверный буквенный ввод"
            y3, m3, d3 = None, None, None
    if y3 and m3 and d3:
        try:
            h_obj = dates.HebrewDate(y3, m3, d3)
            py_d = h_obj.to_pydate()
            j3 = gregorian_to_jdn(py_d.year, py_d.month, py_d.day)
            st.metric(L[14], f"DY{j3//360}-{(j3%360)+1:03d}")
            st.success(f"{L[13]} {jdn_to_gregorian(j3, choice)}")
            st.subheader(f"{L[12]}: {h_obj.year}-{h_obj.month}-{h_obj.day} ({h_obj.hebrew_date_string()})")
        except: st.error(L[6])

# Note: Ayalon model demo moved to `traffic_app.py` (live monitor). The old interactive Ayalon tab was removed to avoid conflicting model interfaces.

st.sidebar.markdown("---")
st.sidebar.markdown("[Dikenocracy ENG](https://github.com/anahronic/World/blob/main/Dikenocracy/Dikenocracy%20%E2%80%94%20CODE%20OF%20PLANETARY%20SYNERGY%20of%20the%20Brotherhood.pdf)")
st.sidebar.markdown("[DKP-0-ORACLE-001 | L0 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L0_Physical_Truth/DKP-0-ORACLE-001)")
st.sidebar.markdown("[DKP-0-TIME-001 | L0 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L0_Physical_Truth/DKP-0-TIME-001)")
st.sidebar.markdown("[DKP-1-AXIOMS-001 | L1 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L1_Core/DKP-1-AXIOMS-001)")
st.sidebar.markdown("[DKP-1-IDENTITY-001 | L1 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L1_Core/DKP-1-IDENTITY-001)")
st.sidebar.markdown("[DKP-1-IMPACT-001 | L1 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L1_Core/DKP-1-IMPACT-001)")
st.sidebar.markdown("[DKP-1-JUSTICE-001 | L1 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L1_Core/DKP-1-JUSTICE-001)")
st.sidebar.markdown("[DKP-2-ASSETS-001 | L2 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L2_Economic/DKP-2-ASSETS-001)")
st.sidebar.markdown("[DKP-2-FINANCE-001 | L2 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L2_Economic/DKP-2-FINANCE-001)")
st.sidebar.markdown("[DKP-2-LABOR-001 | L2 Layer](https://github.com/anahronic/World/blob/main/Dikenocracy/Protocols/L2_Economic/DKP-2-LABOR-001)")