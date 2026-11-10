"""Schutz der localhost-Anwendung gegen Angriffe über fremde Webseiten im Browser.

- DNS-Rebinding: nur Anfragen an erlaubte Hostnamen (localhost, 127.0.0.1, ::1, ...)
- CSRF: API-Anfragen von fremden Seiten werden über Origin / Sec-Fetch-Site abgewiesen;
  ändernde Anfragen müssen JSON senden (erzwingt bei fremden Seiten einen CORS-Preflight,
  den die App nie erlaubt)
- Sicherheits-Header: CSP, Clickjacking-Schutz, nosniff, Referrer-Policy

Kommandozeilen-Clients wie waytimetrack (urllib, curl) senden weder Origin noch
Sec-Fetch-Site und sind daher nicht betroffen, solange sie eine erlaubte Adresse
benutzen und ändernde Anfragen als JSON schicken.
"""
from __future__ import annotations

from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
WILDCARD_LISTEN = {"", "0.0.0.0", "::", "*"}
MAX_REQUEST_BYTES = 20 * 1024 * 1024  # Datensicherungen: viele Jahre passen bequem hinein

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def allowed_hosts(env) -> set[str]:
    """Erlaubte Hostnamen: localhost-Varianten, eine konkrete Listen-Adresse und
    zusätzliche Namen aus TIMETRACK_ALLOWED_HOSTS (kommagetrennt)."""
    hosts = set(LOCAL_HOSTS)
    listen = env.get("TIMETRACK_LISTEN", "127.0.0.1").strip("[]").lower()
    if listen not in WILDCARD_LISTEN:
        hosts.add(listen)
    hosts.update(h.strip().strip("[]").lower()
                 for h in env.get("TIMETRACK_ALLOWED_HOSTS", "").split(",") if h.strip())
    return hosts


def host_name(host_header: str) -> str:
    """Hostname ohne Port aus einem Host-Header ('[::1]:54321' -> '::1')."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h


def check_request(req, hosts: set[str]) -> str | None:
    """Liefert eine Fehlermeldung, wenn die Anfrage abgewiesen werden muss."""
    if host_name(req.host) not in hosts:
        return "Unbekannter Host – timetrack ist nur über localhost erreichbar."
    if not req.path.startswith("/api/"):
        return None

    origin = req.headers.get("Origin")
    if origin is not None:
        own = f"{req.scheme}://{req.host}".lower()
        parts = urlsplit(origin.lower())
        if origin == "null" or f"{parts.scheme}://{parts.netloc}" != own:
            return "Anfrage von fremder Seite abgewiesen."
    site = req.headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        return "Anfrage von fremder Seite abgewiesen."

    if req.method not in ("GET", "HEAD", "OPTIONS") and req.mimetype != "application/json":
        return "Ändernde Anfragen müssen als JSON (Content-Type: application/json) gesendet werden."
    return None


def add_headers(resp):
    for name, value in SECURITY_HEADERS.items():
        resp.headers.setdefault(name, value)
    return resp
