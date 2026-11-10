"""Reine Berechnungslogik: Arbeitszeiten, gesetzliche Pausen, Salden, Markierungen.

Alle Zeiten sind Sekunden (int). Diese Datei greift nicht auf die Datenbank zu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SIX_H = 6 * 3600
NINE_H = 9 * 3600
PAUSE_6H = 30 * 60  # §4 ArbZG: mehr als 6 h Arbeit -> 30 min Pause
PAUSE_9H = 45 * 60  # mehr als 9 h Arbeit -> 45 min Pause

DEFAULT_WEEKLY_MINUTES = 40 * 60
DEFAULT_VACATION_DAYS = 30.0

MARKS = ("TU", "AU", "EGZ", "NF")

# Markierungen (Flags) eines Tages
F_OPEN = "open"            # rot: letzter Eintrag ist "work"
F_MISSING = "missing"      # grau: Arbeitstag ohne Eintrag
F_PAUSE = "pause_short"    # gelb: zu wenig Pause eingetragen
F_OVER9 = "over9"          # gelb: mehr als 9 h Arbeit
F_TU_OVER = "tu_over"      # orange: mehr Urlaub als verfügbar
F_EGZ_NEG = "egz_neg"      # orange: Gleitzeittag im/ins Minus
F_MINUS_NEG = "minus_neg"  # orange: Tag mit Minusstunden erzeugt negatives Konto


@dataclass
class YearCfg:
    vacation_days: float = DEFAULT_VACATION_DAYS
    weekly_minutes: float = DEFAULT_WEEKLY_MINUTES

    @property
    def daily_target(self) -> int:
        return round(self.weekly_minutes * 60 / 5)


@dataclass
class DayResult:
    day: date
    stamps: int = 0
    gross: int = 0          # Summe Arbeitsintervalle
    pause: int = 0          # eingetragene Pausen zwischen Arbeitsintervallen
    deduction: int = 0      # automatischer gesetzlicher Pausenabzug
    net: int = 0            # angerechnete Arbeitszeit
    open: bool = False      # letzter Eintrag "work"
    running: bool = False   # heute, Arbeit läuft gerade
    target: int = 0         # Sollzeit
    mark: str | None = None
    mark_note: str | None = None
    delta: int = 0          # Beitrag zum Überstundenkonto
    counted: bool = False   # fließt ins Überstundenkonto ein
    balance_after: int | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.day.isoformat(),
            "weekday": self.day.weekday(),
            "stamps": self.stamps,
            "gross": self.gross,
            "pause": self.pause,
            "deduction": self.deduction,
            "net": self.net,
            "open": self.open,
            "running": self.running,
            "target": self.target,
            "mark": self.mark,
            "mark_note": self.mark_note,
            "delta": self.delta,
            "counted": self.counted,
            "balance_after": self.balance_after,
            "flags": self.flags,
        }


def legal_net(gross: int, pause: int) -> int:
    """Arbeitszeit nach automatischem Pausenabzug gemäß §4 ArbZG.

    Bereits eingetragene Pausen werden angerechnet. Es wird nur so viel abgezogen,
    dass die Arbeitszeit nicht unter die jeweilige Schwelle (6 h / 9 h) fällt.
    """
    need30 = max(0, PAUSE_6H - pause)
    need45 = max(0, PAUSE_9H - pause)
    if gross > NINE_H:
        return min(gross - need30, max(NINE_H, gross - need45))
    if gross > SIX_H:
        return max(SIX_H, gross - need30)
    return gross


def work_intervals(stamps: list[tuple[datetime, str]], now: datetime | None = None):
    """Liefert (Intervalle, offen, Beginn des offenen Intervalls).

    stamps: nach Zeit sortierte (Zeitpunkt, 'work'|'pause'). Doppelte Einträge
    desselben Typs hintereinander werden ignoriert. Ist ``now`` gesetzt, zählt ein
    offenes Arbeitsintervall bis ``now``.
    """
    res = []
    start = None
    for ts, kind in stamps:
        if kind == "work":
            if start is None:
                start = ts
        elif start is not None:
            res.append((start, ts))
            start = None
    open_ = start is not None
    if open_ and now is not None and now > start:
        res.append((start, now))
    return res, open_, start


def day_times(stamps, now=None) -> tuple[int, int, int, int, bool]:
    """(brutto, pause, abzug, netto, offen) für die Stempel eines Tages."""
    iv, open_, _ = work_intervals(stamps, now)
    gross = sum(int((b - a).total_seconds()) for a, b in iv)
    pause = sum(int((iv[i + 1][0] - iv[i][1]).total_seconds()) for i in range(len(iv) - 1))
    net = legal_net(gross, pause)
    return gross, pause, gross - net, net, open_


def target_for(d: date, mark: str | None, cfg: YearCfg) -> int:
    if d.weekday() >= 5 or mark == "NF":
        return 0
    return cfg.daily_target


class Ledger:
    """Berechnet alle Tage ab Startdatum inkl. Salden und Markierungen."""

    def __init__(self, *, start_date: date, start_balance: int, years: dict[int, YearCfg],
                 stamps: dict[date, list[tuple[datetime, str]]],
                 marks: dict[date, tuple[str, str | None]], now: datetime):
        self.start_date = start_date
        self.start_balance = start_balance
        self.years = years
        self.stamps = stamps
        self.marks = marks
        self.now = now
        self.today = now.date()
        self.days: dict[date, DayResult] = {}
        self.balance = start_balance          # Kontostand bis gestern (+ Tagesart heute)
        self.vacation: dict[int, dict] = {}
        self._run()

    def year_cfg(self, y: int) -> YearCfg:
        if y in self.years:
            return self.years[y]
        earlier = [k for k in self.years if k < y]
        if earlier:
            return self.years[max(earlier)]
        later = [k for k in self.years if k > y]
        return self.years[min(later)] if later else YearCfg()

    def day(self, d: date) -> DayResult:
        """Ergebnis für einen beliebigen Tag (auch vor dem Startdatum)."""
        if d in self.days:
            return self.days[d]
        return self._build(d)

    def _build(self, d: date) -> DayResult:
        mark, note = self.marks.get(d, (None, None))
        st = self.stamps.get(d, [])
        r = DayResult(day=d, stamps=len(st), mark=mark, mark_note=note)
        is_today = d == self.today
        r.gross, r.pause, r.deduction, r.net, r.open = day_times(st, self.now if is_today else None)
        if r.open and is_today:
            r.running = True
            r.open = False
        r.target = target_for(d, mark, self.year_cfg(d.year))
        credit = r.target if mark in ("TU", "AU") else 0
        r.delta = r.net + credit - r.target
        if r.open:
            r.flags.append(F_OPEN)
        if d >= self.start_date:
            if r.deduction > 0:
                r.flags.append(F_PAUSE)
            if r.net > NINE_H:
                r.flags.append(F_OVER9)
            if d < self.today and not st and not mark and r.target > 0:
                r.flags.append(F_MISSING)
        return r

    def _run(self):
        last = self.today
        for d in list(self.stamps) + list(self.marks):
            if d > last:
                last = d
        d = self.start_date
        running = self.start_balance
        counted: list[DayResult] = []
        while d <= last:
            r = self._build(d)
            # Heute zählt erst am Folgetag (sonst wäre das Konto morgens im Minus),
            # außer es ist eine Tagesart (TU/AU/EGZ/NF) eingetragen.
            has_entry = r.stamps > 0 or r.mark is not None
            if d < self.today or (d == self.today and r.mark) or (d > self.today and has_entry):
                r.counted = True
                running += r.delta
                r.balance_after = running
                counted.append(r)
            if d <= self.today:
                self.balance = running
            self.days[d] = r
            d += timedelta(days=1)

        # Orange: Minus-/EGZ-Tage, solange das Konto seitdem nicht wieder >= 0 war
        recovered = False
        for r in reversed(counted):
            if r.balance_after < 0 and not recovered:
                if r.mark == "EGZ":
                    r.flags.append(F_EGZ_NEG)
                elif r.delta < 0:
                    r.flags.append(F_MINUS_NEG)
            if r.balance_after >= 0:
                recovered = True

        # Urlaub: Jahreskontingent + Übertrag, chronologisch verbraucht
        carry = 0.0
        for y in range(self.start_date.year, last.year + 1):
            cfg = self.year_cfg(y)
            available = cfg.vacation_days + carry
            used = 0.0
            taken = 0.0
            d = date(y, 1, 1)
            while d.year == y:
                mark, _ = self.marks.get(d, (None, None))
                if mark == "TU" and d.weekday() < 5:
                    used += 1
                    if d <= self.today:
                        taken += 1
                    if used > available:
                        r = self.days.get(d) or self._build(d)
                        r.flags.append(F_TU_OVER)
                        self.days.setdefault(d, r)
                d += timedelta(days=1)
            self.vacation[y] = {
                "vacation_days": cfg.vacation_days,
                "carry_in": carry,
                "available": available,
                "taken": taken,
                "planned": used - taken,
                "remaining": available - used,
            }
            carry = available - used

    def vacation_for(self, y: int) -> dict:
        if y in self.vacation:
            return self.vacation[y]
        cfg = self.year_cfg(y)
        carry = 0.0
        if y > self.start_date.year and self.vacation:
            carry = self.vacation[max(self.vacation)]["remaining"]
        return {"vacation_days": cfg.vacation_days, "carry_in": carry,
                "available": cfg.vacation_days + carry, "taken": 0.0, "planned": 0.0,
                "remaining": cfg.vacation_days + carry}

    def year_overtime(self, y: int) -> int:
        """Veränderung des Überstundenkontos im Jahr y (bis heute)."""
        return sum(r.delta for d, r in self.days.items()
                   if d.year == y and r.counted and d <= self.today)
