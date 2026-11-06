from datetime import date, datetime

from timetrack import calc, holidays
from timetrack.calc import Ledger, YearCfg, legal_net

H = 3600
M = 60


def test_legal_net():
    assert legal_net(5 * H, 0) == 5 * H
    assert legal_net(6 * H, 0) == 6 * H
    assert legal_net(6 * H + 10 * M, 0) == 6 * H            # gekappt auf 6 h
    assert legal_net(7 * H, 0) == 6 * H + 30 * M
    assert legal_net(7 * H, 30 * M) == 7 * H                 # Pause schon eingetragen
    assert legal_net(7 * H, 20 * M) == 6 * H + 50 * M
    assert legal_net(9 * H + 10 * M, 0) == 8 * H + 40 * M
    assert legal_net(9 * H + 10 * M, 30 * M) == 9 * H
    assert legal_net(10 * H, 30 * M) == 9 * H + 45 * M
    assert legal_net(10 * H, 45 * M) == 10 * H


def test_holidays_ni():
    h = holidays.holidays(2026, "NI")
    assert date(2026, 4, 3) in h       # Karfreitag
    assert date(2026, 5, 14) in h      # Himmelfahrt
    assert date(2026, 10, 31) in h     # Reformationstag
    assert date(2026, 6, 4) not in h   # Fronleichnam nicht in NI
    assert len(h) == 10
    assert holidays.easter_sunday(2027) == date(2027, 3, 28)
    assert date(2026, 11, 18) in holidays.holidays(2026, "SN")  # Buß- und Bettag


def ts(d, hm):
    h, m = map(int, hm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def day(d, *pairs):
    out = []
    for hm, k in pairs:
        out.append((ts(d, hm), k))
    return out


def make(stamps=None, marks=None, now=datetime(2026, 11, 6, 12, 0), start=date(2026, 11, 2),
         balance=0, weekly=40 * 60, vac=30):
    return Ledger(start_date=start, start_balance=balance,
                  years={2026: YearCfg(vac, weekly), 2027: YearCfg(vac, weekly)},
                  stamps=stamps or {}, marks=marks or {}, now=now)


def test_basic_balance_and_flags():
    mon, tue, wed, thu, fri = (date(2026, 11, d) for d in range(2, 7))
    stamps = {
        mon: day(mon, ("08:00", "work"), ("12:00", "pause"), ("12:30", "work"), ("17:00", "pause")),  # 8.5h
        tue: day(tue, ("08:00", "work"), ("15:00", "pause")),   # 7h ohne Pause -> 6.5h, gelb
        thu: day(thu, ("08:00", "work")),                       # vergessen -> rot
        fri: day(fri, ("08:00", "work")),                       # heute, läuft (4h)
    }
    L = make(stamps)
    assert L.day(mon).net == 8 * H + 30 * M and L.day(mon).delta == 30 * M
    assert calc.F_PAUSE in L.day(tue).flags and L.day(tue).net == 6 * H + 30 * M
    assert calc.F_MISSING in L.day(wed).flags
    assert calc.F_OPEN in L.day(thu).flags and L.day(thu).net == 0
    assert L.day(fri).running and L.day(fri).net == 4 * H and not L.day(fri).flags
    # 0.5 - 1.5 - 8 - 8 = -17h (heute zählt noch nicht)
    assert L.balance == -17 * H
    assert L.day(fri).delta == -4 * H and not L.day(fri).counted
    assert calc.F_MINUS_NEG not in L.day(mon).flags
    for d in (tue, wed, thu):
        assert calc.F_MINUS_NEG in L.day(d).flags


def test_orange_cleared_after_recovery():
    mon, tue, sat = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 7)
    stamps = {
        mon: day(mon, ("08:00", "work"), ("14:00", "pause")),             # -2h
        sat: day(sat, ("08:00", "work"), ("12:00", "pause")),             # Wochenende +4h
    }
    marks = {tue: ("TU", None), date(2026, 11, 4): ("TU", None), date(2026, 11, 5): ("TU", None),
             date(2026, 11, 6): ("TU", None)}
    L = make(stamps, marks, now=datetime(2026, 11, 8, 20, 0))
    assert L.day(sat).delta == 4 * H
    assert L.balance == 2 * H
    assert calc.F_MINUS_NEG not in L.day(mon).flags  # wieder im Plus


def test_egz_and_planned():
    mon = date(2026, 11, 2)
    fut = date(2026, 11, 20)
    stamps = {mon: day(mon, ("07:00", "work"), ("12:00", "pause"), ("12:30", "work"), ("17:00", "pause"))}  # +1.5h
    marks = {date(2026, 11, d): ("TU", None) for d in (3, 4, 5, 6)}
    marks[fut] = ("EGZ", None)
    L = make(stamps, marks, now=datetime(2026, 11, 6, 18, 0))
    assert L.balance == 75 * M  # 9.5h brutto, 30 min Pause -> 15 min Abzug
    assert L.day(fut).delta == -8 * H
    assert calc.F_EGZ_NEG in L.day(fut).flags   # geplanter EGZ erzeugt Minus


def test_vacation_over_and_carry():
    marks = {}
    d = date(2026, 11, 2)
    n = 0
    while n < 4:
        if d.weekday() < 5:
            marks[d] = ("TU", None)
            n += 1
        d = date.fromordinal(d.toordinal() + 1)
    L = make(marks=marks, vac=3, start=date(2026, 1, 1))
    over = [x for x in marks if calc.F_TU_OVER in L.day(x).flags]
    assert len(over) == 1
    assert L.vacation[2026]["remaining"] == -1
    L2 = make(marks={date(2026, 11, 2): ("TU", None)}, vac=30, start=date(2026, 1, 1))
    assert L2.vacation_for(2027)["carry_in"] == 29
    assert L2.vacation_for(2027)["available"] == 59


def test_holiday_and_weekend():
    nf = date(2026, 10, 30)  # Freitag, als Feiertag markiert
    L = make(marks={nf: ("NF", "Test")}, start=date(2026, 10, 30), now=datetime(2026, 11, 2, 7, 0))
    assert L.day(nf).target == 0 and calc.F_MISSING not in L.day(nf).flags
    assert L.balance == 0  # Wochenende ohne Soll, heute ohne Eintrag zählt nicht


def test_over9():
    mon = date(2026, 11, 2)
    stamps = {mon: day(mon, ("07:00", "work"), ("12:00", "pause"), ("12:45", "work"), ("17:30", "pause"))}
    L = make(stamps)
    assert L.day(mon).net == 9 * H + 45 * M
    assert calc.F_OVER9 in L.day(mon).flags and calc.F_PAUSE not in L.day(mon).flags
