"""Excel-Export: ein Reiter je Kalendermonat mit Tageszeilen und Monatsstatistik."""
from __future__ import annotations

import io
from datetime import date, timedelta

import xlsxwriter

from . import calc

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MARK_TEXT = {"TU": "Urlaub", "AU": "Krankschreibung", "EGZ": "Gleitzeittag", "NF": "Feiertag"}
COLUMNS = [("Datum", 12), ("Wochentag", 12), ("Tagesart", 18), ("Arbeitsbeginn", 13),
           ("Arbeitsende", 12), ("Arbeitsphasen", 34), ("Arbeitszeit", 12), ("Pausenzeit", 11),
           ("Gesetzl. Pausenabzug", 20), ("Hinweis", 40)]


def years_back(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29. Februar
        return d.replace(year=d.year - years, day=28)


def fmt_signed(sec: int) -> str:
    sign = "-" if sec < 0 else "+"
    m = abs(sec) // 60
    return f"{sign}{m // 60}:{m % 60:02d} h"


def _month_days(y: int, m: int, start: date, end: date) -> list[date]:
    d = max(date(y, m, 1), start)
    out = []
    while d.month == m and d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def build_xlsx(ledger: calc.Ledger, start: date, end: date) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    f_title = wb.add_format({"bold": True, "font_size": 14})
    f_label = wb.add_format({"bold": True})
    f_head = wb.add_format({"bold": True, "bg_color": "#D9DCE2", "border": 1})
    f_date = wb.add_format({"num_format": "dd.mm.yyyy"})
    f_dur = wb.add_format({"num_format": "[h]:mm"})
    f_text = wb.add_format({})
    f_note = wb.add_format({"italic": True, "font_color": "#646B78"})
    f_off = {k: wb.add_format({**props, "bg_color": "#ECEEF1"}) for k, props in {
        "date": {"num_format": "dd.mm.yyyy"}, "dur": {"num_format": "[h]:mm"}, "text": {}}.items()}
    f_on = {"date": f_date, "dur": f_dur, "text": f_text}

    sheets = 0
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        days = _month_days(y, m, start, end)
        results = [ledger.day(d) for d in days]
        if any(r.stamps or r.mark in ("TU", "AU", "EGZ") for r in results):
            _write_month(wb, y, m, days, results, ledger, f_title, f_label, f_head, f_dur,
                         f_note, f_on, f_off)
            sheets += 1
        m += 1
        if m > 12:
            y, m = y + 1, 1

    if not sheets:
        ws = wb.add_worksheet("Keine Daten")
        ws.write(0, 0, f"Keine Einträge zwischen {start:%d.%m.%Y} und {end:%d.%m.%Y}.")
    wb.close()
    return buf.getvalue()


def _write_month(wb, y, m, days, results, ledger, f_title, f_label, f_head, f_dur, f_note,
                 f_on, f_off):
    ws = wb.add_worksheet(f"{MONTHS[m - 1]} {y}")
    ws.write(0, 0, f"{MONTHS[m - 1]} {y}", f_title)

    overtime = sum(r.delta for r in results if r.counted)
    work = sum(r.net for r in results)
    vacation = sum(1 for r in results if r.mark == "TU" and r.day.weekday() < 5)
    sick = sum(1 for r in results if r.mark == "AU")
    ws.write(2, 0, "Überstunden im Monat", f_label)
    ws.write(2, 2, fmt_signed(overtime))
    ws.write(3, 0, "Gesamtarbeitszeit", f_label)
    ws.write_number(3, 2, work / 86400, f_dur)
    ws.write(4, 0, "Genutzte Urlaubstage", f_label)
    ws.write_number(4, 2, vacation)
    ws.write(5, 0, "Krankheitstage", f_label)
    ws.write_number(5, 2, sick)

    notes = []
    if days[0].day != 1:
        notes.append(f"Zeitraum ab {days[0]:%d.%m.%Y}.")
    if any(d == ledger.today for d in days):
        notes.append("Der heutige Tag ist in den Überstunden noch nicht enthalten.")
    if any(d < ledger.start_date for d in days):
        notes.append(f"Überstunden werden erst ab dem Startdatum {ledger.start_date:%d.%m.%Y} gezählt.")
    if notes:
        ws.write(6, 0, " ".join(notes), f_note)

    head = 8
    for col, (name, width) in enumerate(COLUMNS):
        ws.write(head, col, name, f_head)
        ws.set_column(col, col, width)
    ws.freeze_panes(head + 1, 0)

    for i, r in enumerate(results):
        row = head + 1 + i
        d = r.day
        fmt = f_off if d.weekday() >= 5 or r.mark == "NF" else f_on
        is_today = d == ledger.today
        iv, open_, _ = calc.work_intervals(ledger.stamps.get(d, []),
                                           ledger.now if is_today else None)
        phases = [f"{a:%H:%M}–{b:%H:%M}" for a, b in iv]
        hints = []
        if open_ and is_today:
            phases[-1] = phases[-1].split("–")[0] + "–(läuft)"
            hints.append("Arbeit läuft noch")
        elif open_:
            hints.append("Arbeitsende fehlt (nicht ausgestempelt)")
        if r.mark_note and r.mark == "NF":
            hints.append(r.mark_note)
        if r.net > calc.NINE_H:
            hints.append("Mehr als 9 h Arbeitszeit")

        ws.write_datetime(row, 0, d, fmt["date"])
        ws.write(row, 1, WEEKDAYS[d.weekday()], fmt["text"])
        ws.write(row, 2, MARK_TEXT.get(r.mark, ""), fmt["text"])
        if iv:
            ws.write(row, 3, f"{iv[0][0]:%H:%M}", fmt["text"])
            ws.write(row, 4, "" if open_ else f"{iv[-1][1]:%H:%M}", fmt["text"])
        else:
            ws.write_blank(row, 3, None, fmt["text"])
            ws.write_blank(row, 4, None, fmt["text"])
        ws.write(row, 5, ", ".join(phases), fmt["text"])
        if r.stamps:
            ws.write_number(row, 6, r.net / 86400, fmt["dur"])
            ws.write_number(row, 7, r.pause / 86400, fmt["dur"])
            ws.write_number(row, 8, r.deduction / 86400, fmt["dur"])
        else:
            for col in (6, 7, 8):
                ws.write_blank(row, col, None, fmt["dur"])
        ws.write(row, 9, "; ".join(hints), fmt["text"])
