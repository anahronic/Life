# History data (GitHub Actions)

This folder is used by the scheduled GitHub Actions workflow to persist collected monitoring history.

- SQLite DB: `monitor.sqlite3`
- The workflow runs `python collector.py --once` on a schedule and commits updates to this folder.

Notes:
- GitHub Pages cannot run the Streamlit app; this is only for data collection.
- The DB can grow over time. For an MVP (~6 months) this is usually fine.
