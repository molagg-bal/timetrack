-- Migration einer timetrack-Datenbank von Schema v1 (vor Dezimalwerten/Kommentaren) auf v3.
--
-- Normalerweise NICHT nötig: timetrack führt diese Schritte beim ersten Start der neuen
-- Version selbst aus. Das Skript ist für den Fall gedacht, dass du die Datenbank lieber
-- selbst vorab umstellen willst. Es kann gefahrlos mehrfach ausgeführt werden.
--
-- Aufruf auf dem NixOS-Rechner:
--   sudo mysql timetrack < v1-zu-v3.sql

-- v2: Urlaubstage und Wochenstunden mit bis zu zwei Nachkommastellen
ALTER TABLE years
  MODIFY vacation_days DECIMAL(5,2) NOT NULL,
  MODIFY weekly_minutes DECIMAL(7,2) NOT NULL;

-- v3: ein Kommentar pro Tag
CREATE TABLE IF NOT EXISTS day_notes (
  day DATE NOT NULL PRIMARY KEY,
  note TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

UPDATE settings SET value = '3' WHERE name = 'schema_version';
