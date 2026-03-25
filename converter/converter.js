/**
 * converter.js — DTI Time Converter core logic
 *
 * Pure-JS implementation of:
 *   • Gregorian ↔ JDN (integer-only, DKP-0-TIME-001)
 *   • JDN ↔ DTI (360-day year)
 *   • Hebrew calendar ↔ JDN (full Gauss/RD algorithm)
 *   • Hebrew gematria input parsing
 *
 * Zero dependencies. All arithmetic is integer-only where specified.
 */
'use strict';

const DTI_YEAR_DAYS = 360;

/* ═══════════════════════════════════════════════════════════════════════════
 *  GREGORIAN ↔ JDN
 * ═══════════════════════════════════════════════════════════════════════════ */

function gregorianToJdn(year, month, day) {
  if (year === 0) throw new Error('Year 0 does not exist');
  if (month < 1 || month > 12) throw new Error('Month must be 1–12');
  if (day < 1 || day > 31) throw new Error('Day must be 1–31');
  let y = year;
  if (y < 0) y += 1; // astronomical year numbering
  const a = Math.floor((14 - month) / 12);
  const y2 = y + 4800 - a;
  const m2 = month + 12 * a - 3;
  return day + Math.floor((153 * m2 + 2) / 5) +
         365 * y2 + Math.floor(y2 / 4) -
         Math.floor(y2 / 100) + Math.floor(y2 / 400) - 32045;
}

function jdnToGregorian(jdn) {
  const a = jdn + 32044;
  const b = Math.floor((4 * a + 3) / 146097);
  const c = a - Math.floor((146097 * b) / 4);
  const d = Math.floor((4 * c + 3) / 1461);
  const e = c - Math.floor((1461 * d) / 4);
  const m = Math.floor((5 * e + 2) / 153);
  const day = e - Math.floor((153 * m + 2) / 5) + 1;
  const month = m + 3 - 12 * Math.floor(m / 10);
  let year = 100 * b + d - 4800 + Math.floor(m / 10);
  if (year <= 0) year -= 1;
  return { year, month, day };
}

function isValidGregorian(y, m, d) {
  if (y === 0 || y < -5000 || y > 5000) return false;
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  if (y > 0) {
    // Check actual day count
    const daysInMonth = [0,31,28,31,30,31,30,31,31,30,31,30,31];
    if ((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0) daysInMonth[2] = 29;
    if (d > daysInMonth[m]) return false;
  }
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  JDN ↔ DTI
 * ═══════════════════════════════════════════════════════════════════════════ */

function jdnToDti(jdn) {
  const dy = Math.floor(jdn / DTI_YEAR_DAYS);
  const doy = (jdn % DTI_YEAR_DAYS) + 1;
  return { dy, doy };
}

function dtiToJdn(dy, doy) {
  if (doy < 1 || doy > 360) throw new Error('DOY must be 1–360');
  return dy * DTI_YEAR_DAYS + (doy - 1);
}

function fmtDti(d) {
  return `DY${d.dy}-${String(d.doy).padStart(3, '0')}`;
}

function fmtGreg(g, lang) {
  lang = lang || 'EN';
  const bcSuffixes = {
    EN:'BC', RU:'до н.э.', HE:'לפנה״ס', AR:'ق.م', ZH:'公元前',
    ES:'a.C.', FR:'av. J.-C.', DE:'v. Chr.', IT:'a.C.', PT:'a.C.'
  };
  if (g.year <= 0) {
    const absY = Math.abs(g.year - 1);
    return `${absY} ${bcSuffixes[lang] || 'BC'}-${String(g.month).padStart(2,'0')}-${String(g.day).padStart(2,'0')}`;
  }
  return `${String(g.year).padStart(4,'0')}-${String(g.month).padStart(2,'0')}-${String(g.day).padStart(2,'0')}`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  HEBREW CALENDAR — Full implementation
 *  Based on the well-known fixed-arithmetic algorithm.
 *  Reference: Dershowitz & Reingold "Calendrical Calculations"
 * ═══════════════════════════════════════════════════════════════════════════ */

/** Hebrew epoch: JDN of 1 Tishrei 1 (Hebrew year 1) = 347997 */
const HEBREW_EPOCH = 347997;

/** Return true if Hebrew year is a leap year (has Adar II). */
function hebrewLeapYear(year) {
  return ((7 * year + 1) % 19) < 7;
}

/**
 * Number of months in a Hebrew year.
 */
function hebrewMonthsInYear(year) {
  return hebrewLeapYear(year) ? 13 : 12;
}

/**
 * Delay of Rosh Hashana (parts-based).
 * "Molad" of Tishrei for Hebrew year.
 */
function hebrewElapsedDays(year) {
  const monthsElapsed = Math.floor((235 * year - 234) / 19);
  const partsElapsed = 12084 + 13753 * monthsElapsed;
  let day = 29 * monthsElapsed + Math.floor(partsElapsed / 25920);
  // Postponement rules
  if ((3 * (day + 1)) % 7 < 3) day += 1;
  return day;
}

/**
 * Length of a Hebrew year in days.
 */
function hebrewYearLength(year) {
  return hebrewElapsedDays(year + 1) - hebrewElapsedDays(year);
}

/**
 * Days in a specific Hebrew month.
 * Months numbered 1=Tishrei .. 13=Adar II (following pyluach convention for civil year).
 *
 * Internal numbering for this implementation:
 *   1=Tishrei, 2=Cheshvan, 3=Kislev, 4=Tevet, 5=Shevat, 6=Adar (or Adar I),
 *   7=Adar II (leap only), 8=Nisan, 9=Iyyar, 10=Sivan, 11=Tammuz, 12=Av, 13=Elul
 *
 * NOTE: The user's source code uses pyluach ordering where:
 *   1=Nisan, 2=Iyyar, ..., 7=Tishrei, 8=Cheshvan, ..., 12=Adar, 13=Adar II
 * We call this "pyluach order" and the above "civil order".
 */

// Days in months for civil-order (Tishrei=1)
function hebrewMonthDaysCivil(year, month) {
  const yearLen = hebrewYearLength(year);
  const isLeap = hebrewLeapYear(year);

  switch (month) {
    case 1: return 30; // Tishrei
    case 2: return (yearLen % 10 === 5) ? 30 : 29; // Cheshvan: 30 in complete years
    case 3: return (yearLen % 10 === 3) ? 29 : 30; // Kislev: 29 in deficient years
    case 4: return 29; // Tevet
    case 5: return 30; // Shevat
    case 6: return isLeap ? 30 : 29; // Adar I (30 in leap) / Adar (29 in regular)
    case 7: return 29; // Adar II (only in leap years)
    case 8: return 30; // Nisan
    case 9: return 29; // Iyyar
    case 10: return 30; // Sivan
    case 11: return 29; // Tammuz
    case 12: return 30; // Av
    case 13: return 29; // Elul
    default: return 0;
  }
}

/**
 * Hebrew date → JDN.
 * Input: year, month (pyluach order: 1=Nisan..7=Tishrei..13=Adar II), day.
 */
function hebrewToJdn(year, month, day) {
  // Convert pyluach month order to civil month order
  const civilMonth = pyluachToCivilMonth(month, hebrewLeapYear(year));

  // Days from epoch to 1 Tishrei of this year
  let jdn = HEBREW_EPOCH + hebrewElapsedDays(year);

  // Add days for complete months before civilMonth
  const totalMonths = hebrewLeapYear(year) ? 13 : 12;
  for (let m = 1; m < civilMonth; m++) {
    jdn += hebrewMonthDaysCivil(year, m);
  }

  // Add remaining days
  jdn += day - 1;

  return jdn;
}

/**
 * JDN → Hebrew date { year, month (pyluach order), day }.
 */
function jdnToHebrew(jdn) {
  // Approximate year
  let year = Math.floor((jdn - HEBREW_EPOCH) * 19 / 6940) + 1;

  // Adjust: ensure 1 Tishrei of year <= jdn
  while (HEBREW_EPOCH + hebrewElapsedDays(year) > jdn) year--;
  while (HEBREW_EPOCH + hebrewElapsedDays(year + 1) <= jdn) year++;

  const yearStart = HEBREW_EPOCH + hebrewElapsedDays(year);
  let remaining = jdn - yearStart;

  // Find the civil month
  const totalMonths = hebrewLeapYear(year) ? 13 : 12;
  let civilMonth = 1;
  for (let m = 1; m <= totalMonths; m++) {
    const mDays = hebrewMonthDaysCivil(year, m);
    if (remaining < mDays) {
      civilMonth = m;
      break;
    }
    remaining -= mDays;
    if (m === totalMonths) civilMonth = m; // shouldn't happen
  }

  const day = remaining + 1;
  const month = civilToPyluachMonth(civilMonth, hebrewLeapYear(year));

  return { year, month, day };
}

/**
 * Convert pyluach month number (1=Nisan..7=Tishrei..13=Adar II) to
 * civil month number (1=Tishrei..13=Elul).
 */
function pyluachToCivilMonth(pm, isLeap) {
  // Pyluach: 1=Nisan,2=Iyyar,3=Sivan,4=Tammuz,5=Av,6=Elul,
  //          7=Tishrei,8=Cheshvan,9=Kislev,10=Tevet,11=Shevat,12=Adar,13=Adar II
  // Civil:   1=Tishrei,2=Cheshvan,3=Kislev,4=Tevet,5=Shevat,
  //          6=Adar(I),7=Adar II,8=Nisan,9=Iyyar,10=Sivan,11=Tammuz,12=Av,13=Elul
  if (pm >= 7) return pm - 6;   // 7→1, 8→2, ..., 13→7 (but 13 only in leap)
  if (pm <= 6) {
    // Nisan(1)→8, Iyyar(2)→9, ..., Elul(6)→13
    return pm + 7;
  }
  return pm;
}

/**
 * Convert civil month number (1=Tishrei) to pyluach month (1=Nisan).
 */
function civilToPyluachMonth(cm, isLeap) {
  if (cm >= 8)  return cm - 7;  // 8→1, 9→2, ..., 13→6
  if (cm <= 7)  return cm + 6;  // 1→7, 2→8, ..., 7→13
  return cm;
}

/**
 * Number of days in a Hebrew month (pyluach order).
 */
function hebrewMonthDays(year, pyluachMonth) {
  const civilMonth = pyluachToCivilMonth(pyluachMonth, hebrewLeapYear(year));
  return hebrewMonthDaysCivil(year, civilMonth);
}

/**
 * Validate a Hebrew date.
 */
function isValidHebrew(year, month, day) {
  if (year < 1 || year > 9999) return false;
  const isLeap = hebrewLeapYear(year);
  const maxMonth = isLeap ? 13 : 12;
  if (month < 1 || month > maxMonth) return false;
  // In non-leap years, month 13 (Adar II) doesn't exist
  if (!isLeap && month === 13) return false;
  const maxDay = hebrewMonthDays(year, month);
  if (day < 1 || day > maxDay) return false;
  return true;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  HEBREW DATE STRING FORMATTING
 * ═══════════════════════════════════════════════════════════════════════════ */

/** Month names in Hebrew (pyluach order: index 0=unused, 1=Nisan, ..., 13=Adar II) */
const HEBREW_MONTH_NAMES = [
  '', 'ניסן', 'אייר', 'סיון', 'תמוז', 'אב', 'אלול',
  'תשרי', 'חשון', 'כסלו', 'טבת', 'שבט', 'אדר', 'אדר ב׳'
];

/**
 * Convert a number to Hebrew gematria letters.
 * Handles 1–999 range (sufficient for days and year-within-thousands).
 */
function toHebrewGematria(n) {
  if (n <= 0) return String(n);
  const hundreds = ['', 'ק', 'ר', 'ש', 'ת', 'תק', 'תר', 'תש', 'תת', 'תתק'];
  const tens = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ'];
  const ones = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט'];

  // Special cases: 15=ט״ו, 16=ט״ז
  let result = '';
  const h = Math.floor(n / 100);
  const remainder = n % 100;
  const t = Math.floor(remainder / 10);
  const o = remainder % 10;

  if (h > 0 && h <= 9) result += hundreds[h];
  if (remainder === 15) {
    result += 'טו';
  } else if (remainder === 16) {
    result += 'טז';
  } else {
    if (t > 0) result += tens[t];
    if (o > 0) result += ones[o];
  }

  // Add geresh (׳) for single letter, gershayim (״) before last letter for multi
  if (result.length === 1) {
    result += '׳';
  } else if (result.length > 1) {
    result = result.slice(0, -1) + '״' + result.slice(-1);
  }

  return result;
}

/**
 * Format a full Hebrew year in gematria (e.g., 5786 → "תשפ״ו")
 * Typically only the last 3 digits are shown (thousands omitted).
 */
function hebrewYearGematria(year) {
  const withinThousand = year % 1000;
  return toHebrewGematria(withinThousand);
}

/**
 * Format a Hebrew date as a string like "כ״ה אדר תשפ״ו"
 */
function fmtHebrewDateString(year, month, day) {
  const dayStr = toHebrewGematria(day);
  const monthName = HEBREW_MONTH_NAMES[month] || '';
  const yearStr = hebrewYearGematria(year);
  return `${dayStr} ${monthName} ${yearStr}`;
}

/**
 * Format a Hebrew date as "year-month-day" numeric.
 */
function fmtHebrewNumeric(year, month, day) {
  return `${year}-${month}-${day}`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  HEBREW GEMATRIA INPUT PARSING
 * ═══════════════════════════════════════════════════════════════════════════ */

const GEMATRIA_VALUES = {
  'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9,
  'י': 10, 'כ': 20, 'ל': 30, 'מ': 40, 'נ': 50, 'ס': 60, 'ע': 70, 'פ': 80, 'צ': 90,
  'ק': 100, 'ר': 200, 'ש': 300, 'ת': 400,
  // Final forms (same value)
  'ך': 20, 'ם': 40, 'ן': 50, 'ף': 80, 'ץ': 90
};

/**
 * Parse a Hebrew gematria string for a year (always adds 5000).
 */
function fromHebrewNumberYear(s) {
  const cleaned = s.replace(/[״׳"']/g, '');
  let value = 0;
  for (const ch of cleaned) {
    if (GEMATRIA_VALUES[ch] !== undefined) {
      value += GEMATRIA_VALUES[ch];
    }
  }
  value += 5000;
  return value;
}

/**
 * Parse a Hebrew gematria string for a day (no thousands offset).
 */
function fromHebrewNumberDay(s) {
  const cleaned = s.replace(/[״׳"']/g, '');
  let value = 0;
  for (const ch of cleaned) {
    if (GEMATRIA_VALUES[ch] !== undefined) {
      value += GEMATRIA_VALUES[ch];
    }
  }
  return value;
}
