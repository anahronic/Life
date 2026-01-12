# Life

**Project**

- **Description:** A collection of research and tools for traffic and data integration focused on the Ayalon corridor. The primary working folder is [Ayalon_Project](Ayalon_Project/README.md), which contains data parsers, analysis scripts and a small web/CLI interface.

**Quick Start**

- **Create virtualenv:** `python -m venv .venv`
- **Activate (Windows):** `.venv\Scripts\activate`
- **Install dependencies:** `pip install -r Ayalon_Project/requirements.txt`
- **Run main app:** `python Ayalon_Project/app.py` (or try `python Ayalon_Project/traffic_app.py`)
- **Reproduce analysis:** `python Ayalon_Project/run_reproduce.py`

**Tests**

- **Run tests:** `pytest Ayalon_Project/tests` (install `pytest` if not included in requirements)

**Repository Structure (key files)**

- **Ayalon code:** [Ayalon_Project/app.py](Ayalon_Project/app.py), [Ayalon_Project/traffic_app.py](Ayalon_Project/traffic_app.py), [Ayalon_Project/run_reproduce.py](Ayalon_Project/run_reproduce.py)
- **Dependencies:** [Ayalon_Project/requirements.txt](Ayalon_Project/requirements.txt)
- **Raw data:** examples in [Ayalon_Project/raw/tomtom.json](Ayalon_Project/raw/tomtom.json) and other JSON files in `Ayalon_Project/raw`
- **Parsers & cache:** [Ayalon_Project/sources](Ayalon_Project/sources) and cached outputs in [Ayalon_Project/sources/_cache/tomtom_ayalon.json](Ayalon_Project/sources/_cache/tomtom_ayalon.json)
- **Constants:** [Ayalon_Project/LOCKED_CONSTANTS.json](Ayalon_Project/LOCKED_CONSTANTS.json)
- **Tests:** [Ayalon_Project/tests](Ayalon_Project/tests)

**Developer Notes**

- **Caching:** The parsers under [Ayalon_Project/sources](Ayalon_Project/sources) write/read a simple JSON cache in `sources/_cache` to avoid repeated network or heavy parsing.
- **Data sources:** Parsers include TomTom, fuel and local CSV/JSON formats. Raw sources are kept in `Ayalon_Project/raw` for traceability.
- **Reproducibility:** Use `run_reproduce.py` to run the documented sequence from `IMPLEMENTATION_REPORT.md` and `FREEZE_MANIFEST.md`.

**Useful Commands**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r Ayalon_Project/requirements.txt
pytest Ayalon_Project/tests
```
