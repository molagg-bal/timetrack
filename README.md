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
| `services.timetrack.allowedHosts` | `[ ]` | weitere Hostnamen für die Weboberfläche (localhost ist immer erlaubt) |
| `services.timetrack.hardening` | `true` | strenge systemd-Sandbox (nur zur Fehlersuche abschalten) |
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

**Jahre & Einstellungen:** pro Jahr Urlaubstage und Wochenarbeitszeit, beide als
Dezimalzahl mit bis zu zwei Nachkommastellen (Komma oder Punkt, z. B. 39,8 h). Resturlaub wird
automatisch ins Folgejahr übertragen, negativer Rest ebenso. Ein neues Jahr übernimmt
die Werte des Vorjahres. Dazu kommen Startdatum und Startsaldo des Überstundenkontos.

**Kommentar:** In der Tagesansicht gibt es pro Tag ein Kommentarfeld. Im Kalender zeigt
ein `*` an, dass ein Kommentar existiert; der Text selbst steht nur in der Tagesansicht
und im Excel-Export.

**Export & Datensicherung:**
- Excel-Export der letzten zwei Jahre, taggenau ab heute zurückgerechnet. Pro
  Kalendermonat gibt es einen Reiter mit allen Tagen: Tagesart als Text (Urlaub,
  Krankschreibung, Gleitzeittag, Feiertag), Gesamtarbeitszeit, Gesamtpausenzeit
  (eingetragene Pausen plus gesetzlicher Abzug) und Kommentar. Oben steht die
  Monatsstatistik: Überstunden im Monat, Gesamtarbeitszeit, genutzte Urlaubstage und
  Krankheitstage. Monate ohne Zeitstempel, ohne TU/AU/EGZ und ohne Kommentar werden weggelassen.
- Datensicherung: Der gesamte Datenbankinhalt wird als JSON-Datei heruntergeladen.
- Einspielen einer Datensicherung: Nach zwei Sicherheitsabfragen werden alle
  vorhandenen Daten gelöscht und durch die Datei ersetzt. Das geschieht in einer
  Transaktion. Ist die Datei fehlerhaft, bleibt der alte Stand erhalten.

## Rechenregeln

- Soll pro Tag Mo–Fr = Wochenarbeitszeit / 5. Sa/So und NF: Soll 0, jede Arbeit dort sind Überstunden.
- An AU- und EGZ-Tagen ist keine Arbeitszeit möglich: Die Zeiteingabe verschwindet, und
  das Stempeln auf der Startseite ist gesperrt. Stehen an einem Tag schon Zeiten, lässt
  sich AU/EGZ nicht setzen (Fehlermeldung).
- An TU- und NF-Tagen kann gearbeitet werden. Die Arbeitszeit zählt dort komplett als
  Überstunden; der Urlaubstag bleibt verbraucht.
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

## Sicherheit

- **Nur localhost:** Der Webserver lauscht auf 127.0.0.1. Anfragen mit anderem Host-Header
  werden abgewiesen (Schutz vor DNS-Rebinding).
- **Fremde Webseiten** können die API nicht benutzen: Anfragen mit fremdem `Origin` oder
  `Sec-Fetch-Site` werden abgewiesen, ändernde Anfragen nur als JSON angenommen (CSRF-Schutz).
  Kommandozeilen-Clients wie waytimetrack oder curl funktionieren weiter.
- **Browser-Schutz:** Strenge Content-Security-Policy (keine Inline-Skripte), Einbetten in
  fremde Seiten verboten, alle Daten werden beim Anzeigen HTML-maskiert.
- **Excel-Export:** Kommentare werden immer als Text geschrieben, nie als Formel oder Link.
- **Grenzen:** Anfragen höchstens 20 MB; Datensicherungen werden auf Typen und Längen geprüft.
- **Dienst:** Läuft als eigener Benutzer `timetrack` in einer strengen systemd-Sandbox
  (schreibgeschütztes Dateisystem, keine Sonderrechte, nur localhost-Netzwerk).
- **MariaDB:** Lauscht nur auf 127.0.0.1; zusätzlich verwirft systemd alle IP-Pakete, die
  nicht von/zu localhost gehen. timetrack selbst verbindet sich über den Unix-Socket.
- **Lieferkette:** In der `configuration.nix` ein Release-Tag mit Prüfsumme festschreiben:
  `fetchTarball { url = ".../archive/refs/tags/v1.0.0.tar.gz"; sha256 = "..."; }`
  (Prüfsumme mit `nix-prefetch-url --unpack <url>`), vor jedem Update die Änderungen ansehen.

## Update einer bestehenden Installation

Die vorhandene Datenbank wird weiterverwendet. Beim ersten Start einer neuen Version
stellt timetrack das Schema selbst um (Schema-Version steht in `settings`):

- v1 → v2: Urlaubstage und Wochenstunden als Dezimalzahlen
- v2 → v3: Tabelle `day_notes` für Kommentare

Wer die Umstellung lieber selbst vorab ausführen will: `migrations/v1-zu-v3.sql`
(`sudo mysql timetrack < v1-zu-v3.sql`). Ältere Datensicherungen (auch von „timeapp“)
lassen sich weiterhin einspielen.

## Datenbankschema

| Tabelle | Inhalt |
|---|---|
| `stamps(id, ts DATETIME, kind ENUM('work','pause'))` | ein Eintrag je Button-Klick, Index auf `ts` |
| `day_marks(day DATE PK, kind ENUM('TU','AU','EGZ','NF'), note, auto)` | höchstens eine Tagesart je Tag |
| `years(year PK, vacation_days DECIMAL(5,2), weekly_minutes DECIMAL(7,2), holidays_done)` | Jahreseinstellungen |
| `day_notes(day DATE PK, note TEXT)` | ein Kommentar je Tag |
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
