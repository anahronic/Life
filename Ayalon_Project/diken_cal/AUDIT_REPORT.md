# Отчет по аудиту репозитория Ayalon Real-Time Physical Impact Model
**Дата аудита:** 8 января 2026  
**Версия:** v1.0  
**Статус:** Freeze Candidate (требуется устранение выявленных проблем)

---

## 1. Обзор проекта

### Назначение
Приложение для расчета физического воздействия дорожного трафика на шоссе Аялон в режиме реального времени на основе методологии Methodology.md v1.0.

### Технический стек
- **Runtime:** Python 3.10.12
- **UI Framework:** Streamlit 1.52.2
- **Data Processing:** pandas 2.3.3, numpy 2.2.6, openpyxl 3.1.5, xlrd 2.0.2
- **HTTP Client:** requests 2.32.5
- **APIs:** TomTom Traffic Flow, svivaaqm.net Air Quality, Gov.il Fuel Prices
- **Testing:** pytest 6.2.5
- **CI/CD:** GitHub Actions

### Архитектура
```
diken_cal/
├── app.py                    # DTI календарь (отдельное приложение)
├── traffic_app.py            # Streamlit-монитор Ayalon (основной UI)
├── methodology.py            # Ядро модели (детерминистические расчеты)
├── run_reproduce.py          # Еженедельный экспорт для воспроизводимости
├── sources/
│   ├── cache.py              # Файловое кеширование с TTL
│   ├── tomtom.py             # TomTom API клиент
│   ├── sviva.py              # svivaaqm AQ API клиент
│   ├── fuel_govil.py         # Gov.il XLS парсер (production-grade)
├── tests/
│   └── test_model_math.py    # Детерминистический unit-тест
└── .github/workflows/
    ├── ci.yml                # CI на каждый push
    └── reproduce_weekly.yml  # Еженедельный cron-экспорт
```

---

## 2. Результаты аудита (8 команд)

### 2.1. Структура репозитория
```
Команда: tree walk
Результат: 10 директорий, ~25 релевантных файлов
```
**Ключевые файлы:**
- `methodology.py` (132 строки) — ядро модели
- `traffic_app.py` (87 строк) — Streamlit UI
- `sources/fuel_govil.py` (146 строк) — парсер с locked rule
- `sources/tomtom.py` (82 строки) — трафик API
- `tests/test_model_math.py` (16 строк) — unit-тесты
- `README.md`, `requirements.txt`, `.github/workflows/*`

### 2.2. Версия Python и зависимости
```bash
Python 3.10.12
pip freeze: 100+ пакетов
```
**Критичные зависимости:**
- streamlit==1.52.2
- pandas==2.3.3
- requests==2.32.5
- openpyxl==3.1.5
- xlrd==2.0.2 ⚠️ (установлен вручную, НЕ в requirements.txt)
- pyluach==2.3.0 (для DTI календаря)
- pytest==6.2.5

### 2.3. Тесты
```bash
pytest -q
Результат: 1 passed in 0.01s ✅
```
**Покрытие:** `test_model_math.py` проверяет детерминистические выходы модели:
- delta_T_total_h = 950.0
- fuel_excess_L = 1140.0
- leakage_ils = 8550.0
- co2_emissions_kg = 2633.4
- provenance metadata (model_version, constants_version, etc.)

### 2.4. Демо-запуск модели
```bash
python methodology.py
```
**Вывод:**
```
=== Ayalon Model Demo ===
Time dissipation: 950.00 vehicle-hours
Fuel excess: 1140.00 L
Fuel leakage: ₪8,550.00
CO2 emissions: 2,633.40 kg
Provenance: {
  "model_version": "1.0",
  "constants_version": "20260101",
  "data_timestamp_utc": "2026-01-07T10:00:00Z",
  "data_source_ids": ["tomtom:flow:ayalon", "sviva:aq:ayalon_avg", "govil:fuel:95"],
  "pipeline_run_id": "<UUID>"
}
```
✅ Выходные значения совпадают с тестом

### 2.5. Воспроизводимость (reproduce)
```bash
FUEL_PRICE_ILS=7.5 python run_reproduce.py
```
**Результат:**
- ✅ Экспортировано 3 файла: `raw/tomtom.json`, `raw/sviva.json`, `raw/fuel.json`
- ⚠️ Требуется env-переменная `FUEL_PRICE_ILS` из-за ошибки парсера (см. раздел 3.2)
- ⚠️ Изначально упал с `ImportError: xlrd` → установлен вручную

### 2.6. Инспекция ключевых файлов
**Команда:** Вывод 8 файлов с номерами строк

**Основные находки:**
- `methodology.py`: Канонический schema enforced ✅
- `traffic_app.py`: Импортирует `fuel_govil.fetch_current_fuel_price()` ✅
- `sources/fuel_govil.py`: Locked parsing rule (строки 87-104) с токенами `['בנזין','95','שירות']`
- `app.py`: Добавлена функция `jdn_to_ymd()` (строки 55-70) ✅
- `README.md`: Quickstart инструкции ✅
- `requirements.txt`: ⚠️ Отсутствует `xlrd`

### 2.7. Проверка legacy schema drift
```bash
grep -rn "'L':|'T_obs':|'Vehicles':" --include="*.py"
```
**Результат:** 5 совпадений, все в `methodology.py`:
```
methodology.py:60:        Vehicles_i = seg['vehicle_count']
methodology.py:61:        T_obs_s = seg['observed_travel_time_s']
methodology.py:62:        L_km = seg['length_km']
```
✅ Это **внутренние переменные**, не ключи словарей → допустимо  
✅ Все dict keys используют каноническую схему: `segment_id`, `length_km`, `observed_travel_time_s`, `vehicle_count`

### 2.8. Тест live источников
```bash
python - <<'PY'
from sources.tomtom import get_ayalon_segments
from sources.fuel_govil import fetch_current_fuel_price_ils_per_l
...
PY
```
**Результат:**
```
TOMTOM_API_KEY set: False
tomtom keys: dict_keys(['segments', 'source_id', 'fetched_at'])
segments: 3

fuel keys: dict_keys(['source_id', 'fetched_at_utc', 'effective_year_month', 'price_ils_per_l', 'raw'])
price_ils_per_l: 7.5
effective_year_month: 2026-01
```
✅ TomTom возвращает 3 sample-сегмента (без API ключа используется fallback)  
✅ Fuel возвращает env-override значение с правильной схемой

---

## 3. Выявленные проблемы

### 3.1. КРИТИЧНО: xlrd отсутствует в requirements.txt
**Файл:** `requirements.txt`  
**Проблема:** `xlrd==2.0.2` установлен вручную во время аудита, но не добавлен в файл зависимостей  
**Влияние:** CI/CD workflows упадут при попытке прочитать `.xls` файлы Gov.il  
**Приоритет:** HIGH  
**Решение:** Добавить строку `xlrd==2.0.2` в `requirements.txt`

### 3.2. БЛОКЕР: Fuel XLS parsing rule mismatch
**Файл:** `sources/fuel_govil.py`, строки 87-104  
**Проблема:** Locked parsing rule с токенами `['בנזין','95','שירות']` не соответствует актуальной структуре XLS файла Gov.il (январь 2026)  
**Ошибка:**
```python
RuntimeError: Fuel XLS parsing rule mismatch. Expected: ['בנזין', '95', 'שירות'], found: <другие токены>
```
**Влияние:** Парсер намеренно падает (fail-closed approach) вместо возврата некорректных данных. Система работает через env-override `FUEL_PRICE_ILS=7.5`  
**Приоритет:** BLOCKER (для production без env-переменной)  
**Решение:** 
1. Скачать актуальный XLS с `https://www.gov.il/BlobFolder/dynamiccollectorresultitem/fuel_prices_<YYYYMM>.xls`
2. Инспектировать структуру листа (колонки, строки с искомыми токенами)
3. Обновить locked rule в `fuel_govil.py:87-104`

### 3.3. MINOR: Неверный ключ в traffic_app.py
**Файл:** `traffic_app.py`, строка 57  
**Проблема:**
```python
fuel_data.get('source')  # ❌ Неверно
```
**Правильно:**
```python
fuel_data.get('source_id')  # ✅ Согласно схеме fuel_govil.py
```
**Влияние:** Провенанс топлива не отображается в UI  
**Приоритет:** LOW  
**Решение:** Замена 'source' → 'source_id'

### 3.4. OPTIONAL: PROBE_POINTS — sample координаты
**Файл:** `sources/tomtom.py`, строки 10-14  
**Проблема:** Текущие координаты — примеры (La Guardia, Ha Shalom, Arlozorov), не точные GPS-точки шоссе Аялон  
**Влияние:** При использовании реального TomTom API ключа данные могут быть неточными  
**Приоритет:** OPTIONAL (при использовании live API)  
**Решение:** Заменить на точные координаты Аялон + актуальные `length_km` для каждого сегмента

---

## 4. Статус канонической схемы (PTL Compliance)

### 4.1. Canonical Segment Schema
**Требование:** Все сегменты должны иметь ключи:
```python
{
  'segment_id': str,
  'length_km': float,
  'observed_travel_time_s': float,
  'vehicle_count': int
}
```
**Статус:** ✅ ENFORCED
- `methodology.py` sample (строки 120-132): использует каноническую схему
- `sources/tomtom.py` (строки 37-48, 69-76): возвращает canonical segments
- `app.py`: legacy Ayalon demo удален (строка 164)

**Grep audit:** 5 hits — только внутренние переменные, не dict keys ✅

### 4.2. Provenance Metadata
**Требование:** Каждый `run_model()` вывод должен содержать:
```python
{
  "model_version": str,
  "constants_version": str,
  "data_timestamp_utc": str,
  "data_source_ids": List[str],
  "pipeline_run_id": str
}
```
**Статус:** ✅ IMPLEMENTED
- `methodology.py:110-119`: генерирует все поля
- `traffic_app.py:71-76`: отображает provenance в UI
- `test_model_math.py:13-16`: проверяет наличие полей

---

## 5. CI/CD статус

### 5.1. GitHub Actions Workflows
**Файлы:**
- `.github/workflows/ci.yml` — запуск при каждом push
- `.github/workflows/reproduce_weekly.yml` — cron каждое воскресенье

**Шаги CI:**
1. `pip install -r requirements.txt`
2. `pytest`
3. `python run_reproduce.py` (с env-override)

**Текущий статус:** ⚠️ FAILING (из-за отсутствия xlrd в requirements.txt)

### 5.2. Рекомендации
1. Добавить `xlrd==2.0.2` в `requirements.txt`
2. Добавить `FUEL_PRICE_ILS` в GitHub Secrets (временный workaround до исправления парсера)
3. После фикса парсера — удалить env-override из workflow

---

## 6. Рекомендации к исправлению

### Приоритет HIGH (до production)
1. **Добавить xlrd в requirements.txt**
   - Файл: `requirements.txt`
   - Действие: Добавить строку `xlrd==2.0.2`

2. **Исправить fuel_govil.py parsing rule**
   - Файл: `sources/fuel_govil.py:87-104`
   - Действие: Скачать актуальный XLS, инспектировать, обновить токены
   - Альтернатива: Продолжить с env-override до уточнения бизнес-логики

### Приоритет LOW (polish)
3. **Исправить traffic_app.py:57**
   - Замена: `fuel_data.get('source')` → `fuel_data.get('source_id')`

4. **Уточнить PROBE_POINTS в tomtom.py**
   - Если планируется live TomTom API — заменить на точные координаты Аялон

---

## 7. Итоговые метрики

| Метрика | Значение | Статус |
|---------|----------|--------|
| **Unit tests** | 1/1 passed | ✅ |
| **Canonical schema compliance** | 100% (0 violations) | ✅ |
| **Provenance metadata** | Полностью реализовано | ✅ |
| **Dependencies missing** | 1 (xlrd) | ⚠️ |
| **Production blockers** | 1 (fuel parser) | ❌ |
| **Minor bugs** | 1 (traffic_app.py:57) | ⚠️ |
| **CI/CD status** | Failing (xlrd) | ❌ |

---

## 8. Следующие шаги

### Вариант A: Быстрый фикс (2-4 часа)
1. Добавить `xlrd` в requirements.txt
2. Исправить `traffic_app.py:57`
3. Добавить `FUEL_PRICE_ILS=7.5` в GitHub Secrets
4. Задеплоить с env-override

### Вариант B: Полный фикс (1-2 дня)
1. Вариант A (шаги 1-2)
2. Получить и инспектировать актуальный Gov.il XLS за январь 2026
3. Обновить locked parsing rule в `fuel_govil.py`
4. Добавить тест для парсера в `tests/test_fuel_parser.py`
5. Задеплоить без env-override

### Рекомендация
**Вариант B** предпочтителен для production-readiness. Locked parsing rule — правильный подход (fail-closed), но требует точной настройки под актуальный формат данных.

---

## 9. Контакты и ссылки

**Репозиторий:** `/home/anahronic/diken_cal`  
**Методология:** Methodology.md v1.0  
**Аудитор:** GitHub Copilot (Claude Sonnet 4.5)  
**Дата:** 8 января 2026

---

**Конец отчета**
