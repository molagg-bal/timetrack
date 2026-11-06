# timetrack

Arbeitszeiterfassung als lokaler Webserver (Port **54321**): Arbeit/Pause stempeln,
Urlaub (TU), Krankheit (AU), Gleitzeittage (EGZ) und Feiertage (NF) verwalten,
Überstundenkonto und Resturlaub berechnen. Daten liegen in MariaDB/MySQL.

## Installation auf NixOS

In `/etc/nixos/configuration.nix` eine Zeile in die `imports`-Liste:

```nix
imports = [
  ./hardware-configuration.nix
  (fetchTarball "https://github.com/BENUTZERNAME/timetrack/archive/refs/heads/main.tar.gz")
];
```

Danach `sudo nixos-rebuild switch` und http://localhost:54321/ öffnen.

Mehr ist nicht nötig. Der Import aktiviert den Dienst, alle Python-Abhängigkeiten
kommen über das Paket mit. Das Modul aktiviert MariaDB (`services.mysql`, Paket `mariadb`),
legt die Datenbank `timetrack` und den gleichnamigen Benutzer an (Anmeldung über den
Unix-Socket, kein Passwort) und startet `timetrack.service` als eigener Systembenutzer.
Die Tabellen erzeugt die App beim ersten Start selbst.

Hinweise:
- Das GitHub-Repository muss **öffentlich** (Public) sein, sonst schlägt der Download
  beim Rebuild fehl. `BENUTZERNAME` ist dein GitHub-Benutzername.
- Nix lädt den Stand von `main` erneut, wenn der Cache älter als 1 h ist. Updates
  kommen also mit dem nächsten `nixos-rebuild switch`.
- Läuft auf dem Rechner schon eine MySQL/MariaDB über `services.mysql`, wird diese
  mitbenutzt. Es kommen nur Datenbank und Benutzer hinzu.
- Abschalten ohne den Import zu entfernen: `services.timetrack.enable = false;`

### Optionen (alle optional)

| Option | Standard | Bedeutung |
|---|---|---|
| `services.timetrack.port` | `54321` | Port |
| `services.timetrack.listenAddress` | `"127.0.0.1"` | nur lokal erreichbar |
| `services.timetrack.holidayState` | `"NI"` | Bundesland für automatische Feiertage |
| `services.timetrack.database.createLocally` | `true` | MariaDB automatisch einrichten |
| `services.timetrack.database.name` | `"timetrack"` | Datenbankname |
| `services.timetrack.database.socket` | `/run/mysqld/mysqld.sock` | Socket |

Logs: `journalctl -u timetrack`. Backup: `sudo mysqldump timetrack > timetrack.sql`.

## Bedienung

**Stempeln (Startseite):** Der große Button wechselt zwischen PAUSE (rot, Ausgangszustand)
und WORK (grün). Jeder Klick speichert einen Zeitstempel. Darunter stehen die heutige
Arbeits- und Pausenzeit. Nach dem Neuladen zeigt die Seite den gespeicherten Zustand.
Das Menü oben rechts führt zu den anderen Seiten.

**Kalender:** Monatsansicht, jeder Tag zeigt TU/AU/EGZ/NF oder die Arbeitszeit. Klick auf
einen Tag öffnet die Zeitstempel zum Bearbeiten, Löschen und Hinzufügen sowie die Tagesart.
Oben stehen Überstundenkonto und Resturlaub.

Farben:
- **rot**: letzter Eintrag des Tages ist „work“ (Arbeitsende vergessen)
- **orange**: Urlaub über dem verfügbaren Kontingent; EGZ oder Tag mit Minusstunden,
  durch den das Überstundenkonto negativ ist. Die Markierung verschwindet, sobald das
  Konto später wieder ≥ 0 ist. Geplante EGZ in der Zukunft werden ebenfalls geprüft.
- **gelb**: zu wenig Pause eingetragen (gesetzliche Pause wurde abgezogen) oder mehr
  als 9 h Arbeitszeit
- **grau**: vergangener Arbeitstag ohne jeden Eintrag

Trifft mehr als eine Farbe zu, gilt die Reihenfolge rot > orange > gelb > grau; weitere
Markierungen erscheinen als Punkte.

**Jahre & Einstellungen:** pro Jahr Urlaubstage und Wochenarbeitszeit. Resturlaub wird
automatisch ins Folgejahr übertragen, negativer Rest ebenso. Ein neues Jahr übernimmt
die Werte des Vorjahres. Dazu kommen Startdatum und Startsaldo des Überstundenkontos.

**Export & Datensicherung:**
- Excel-Export der letzten zwei Jahre, taggenau ab heute zurückgerechnet. Pro
  Kalendermonat gibt es einen Reiter mit allen Tagen: Arbeitsbeginn/-ende,
  Arbeitsphasen, Arbeitszeit, Pausenzeit, gesetzlicher Pausenabzug und Tagesart als
  Text (Urlaub, Krankschreibung, Gleitzeittag, Feiertag). Oben steht die
  Monatsstatistik: Überstunden im Monat, Gesamtarbeitszeit, genutzte Urlaubstage und
  Krankheitstage. Monate ohne Zeitstempel und ohne TU/AU/EGZ werden weggelassen.
- Datensicherung: Der gesamte Datenbankinhalt wird als JSON-Datei heruntergeladen.
- Einspielen einer Datensicherung: Nach zwei Sicherheitsabfragen werden alle
  vorhandenen Daten gelöscht und durch die Datei ersetzt. Das geschieht in einer
  Transaktion. Ist die Datei fehlerhaft, bleibt der alte Stand erhalten.

## Rechenregeln

- Soll pro Tag Mo–Fr = Wochenarbeitszeit / 5. Sa/So und NF: Soll 0, jede Arbeit dort sind Überstunden.
- TU und AU: Soll gilt als erfüllt. EGZ: Soll wird vom Überstundenkonto abgezogen.
- Arbeitszeit = Summe der Intervalle von „work“ bis zum nächsten „pause“. Pausen sind die
  Lücken zwischen den Arbeitsintervallen.
- Gesetzliche Pause (§4 ArbZG): über 6 h mindestens 30 min, über 9 h mindestens 45 min.
  Eingetragene Pausen werden angerechnet, nur der fehlende Rest wird abgezogen. Dabei
  fällt die Arbeitszeit nie unter die jeweilige Schwelle.
- Das Überstundenkonto zählt bis gestern. Der laufende Tag fließt erst am Folgetag ein
  (die Startseite zeigt ihn separat als „Saldo heute“); eine Tagesart von heute zählt sofort.
- Vergangene Arbeitstage ohne Eintrag zählen als 0 h (Minusstunden).
- Tage vor dem Startdatum zählen nicht.
- Feiertage werden pro Jahr einmalig automatisch als NF eingetragen. Sie lassen sich
  löschen oder ändern, und über „Feiertage“ auf der Jahresseite erneut eintragen.
- Arbeit über Mitternacht wird nicht unterstützt (jeder Tag wird für sich gerechnet).

## Datenbankschema

| Tabelle | Inhalt |
|---|---|
| `stamps(id, ts DATETIME, kind ENUM('work','pause'))` | ein Eintrag je Button-Klick, Index auf `ts` |
| `day_marks(day DATE PK, kind ENUM('TU','AU','EGZ','NF'), note, auto)` | höchstens eine Tagesart je Tag |
| `years(year PK, vacation_days, weekly_minutes, holidays_done)` | Jahreseinstellungen |
| `settings(name PK, value)` | Startdatum, Startsaldo (Sekunden), Schema-Version |

Gespeichert werden nur Rohdaten. Salden, Urlaubsübertrag und Markierungen berechnet die
App bei jeder Anfrage neu, deshalb bleibt nach Korrekturen nichts inkonsistent.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install flask waitress pymysql xlsxwriter pytest openpyxl
.venv/bin/python -m pytest
TIMETRACK_DB_SQLITE=/tmp/dev.db .venv/bin/python -m timetrack   # Testbetrieb ohne MariaDB
```

Paket mit Nix bauen (führt dabei die Tests aus):
`nix-build -E 'with import <nixpkgs> {}; callPackage ./nix/package.nix {}'`
