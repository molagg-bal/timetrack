"""Startpunkt: ``timetrack`` bzw. ``python -m timetrack``."""
import os

from waitress import serve

from .app import create_app
from .db import Database


def main():
    db = Database()
    db.wait_ready()
    db.init_schema()
    app = create_app(db)
    host = os.environ.get("TIMETRACK_LISTEN", "127.0.0.1")
    port = int(os.environ.get("TIMETRACK_PORT", "54321"))
    print(f"timetrack läuft auf http://{host}:{port}/", flush=True)
    serve(app, host=host, port=port, threads=4, ident="timetrack")


if __name__ == "__main__":
    main()
