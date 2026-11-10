# timetrack

Arbeitszeiterfassung: Flask + waitress, MariaDB (mysqlclient), Vanilla-JS-Frontend, NixOS-Modul.

- `timetrack/calc.py`: gesamte Rechenlogik (rein, ohne DB) – Salden, ArbZG-Pausen, Markierungen
- `timetrack/export.py`: Excel-Export (xlsxwriter); Datensicherung als JSON in `db.py` (export_data/import_data)
- `timetrack/app.py`: JSON-API + statische Seiten; `timetrack/db.py`: Schema, Verbindung (MySQL oder SQLite für Tests)
- `timetrack/static/`: index.html, app.js, style.css (Hash-Routing: #/, #/kalender, #/jahre, #/export)
- `default.nix` = NixOS-Modul-Einstieg (importiert nix/module.nix, aktiviert sich selbst); `nix/package.nix`, `nix/module.nix`
- Schema-Migrationen in `Database.init_schema` (SCHEMA_VERSION), manuelles SQL in `migrations/`
- Tests: `.venv/bin/python -m pytest` (venv: flask waitress pymysql xlsxwriter pytest openpyxl)
- Lokal starten ohne MariaDB: `TIMETRACK_DB_SQLITE=/tmp/dev.db .venv/bin/python -m timetrack`
- In der Sandbox gibt es kein Nix und keinen Browser; Nix-Dateien können hier nicht gebaut werden.
