"""Gesetzliche Feiertage in Deutschland, je Bundesland."""
from datetime import date, timedelta

STATES = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg",
    "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz",
    "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein", "TH": "Thüringen",
}


def easter_sunday(year: int) -> date:
    """Gaußsche Osterformel (anonymer gregorianischer Algorithmus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays(year: int, state: str = "NI") -> dict[date, str]:
    state = state.upper()
    easter = easter_sunday(year)
    res = {
        date(year, 1, 1): "Neujahr",
        easter - timedelta(days=2): "Karfreitag",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 12, 25): "1. Weihnachtsfeiertag",
        date(year, 12, 26): "2. Weihnachtsfeiertag",
    }
    if state in ("BW", "BY", "ST"):
        res[date(year, 1, 6)] = "Heilige Drei Könige"
    if (state == "BE" and year >= 2019) or (state == "MV" and year >= 2023):
        res[date(year, 3, 8)] = "Internationaler Frauentag"
    if state == "BB":
        res[easter] = "Ostersonntag"
        res[easter + timedelta(days=49)] = "Pfingstsonntag"
    if state in ("BW", "BY", "HE", "NW", "RP", "SL"):
        res[easter + timedelta(days=60)] = "Fronleichnam"
    if state == "SL":
        res[date(year, 8, 15)] = "Mariä Himmelfahrt"
    if state == "TH" and year >= 2019:
        res[date(year, 9, 20)] = "Weltkindertag"
    if state in ("BB", "MV", "SN", "ST", "TH") or (
        state in ("HB", "HH", "NI", "SH") and year >= 2018
    ):
        res[date(year, 10, 31)] = "Reformationstag"
    if state in ("BW", "BY", "NW", "RP", "SL"):
        res[date(year, 11, 1)] = "Allerheiligen"
    if state == "SN":
        # Mittwoch vor dem 23. November
        d = date(year, 11, 22)
        while d.weekday() != 2:
            d -= timedelta(days=1)
        res[d] = "Buß- und Bettag"
    return dict(sorted(res.items()))
