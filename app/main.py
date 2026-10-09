"""Mini serwis nagran metryk z XC60.

Po co istnieje: progi detektorow w aplikacji sa dobierane z realnych pomiarow,
a dotad kazdy pomiar konczyl sie zdjeciem ekranu, z ktorego trzeba bylo
odczytywac cyfry. To jest ten sam kanal, tylko bez aparatu.

Dwie decyzje projektowe warte uzasadnienia:

1. Probka trafia do bazy jako SWOBODNY JSON, a nie jako kolumny. Zestaw metryk
   w aplikacji zmienia sie co kilka dni - gdyby schemat bazy go odwzorowywal,
   kazda nowa metryka wymagalaby migracji po stronie serwera. Kolumny powstaja
   dopiero przy eksporcie do CSV, z sumy kluczy faktycznie zapisanych probek.

2. Zapis jest IDEMPOTENTNY po (sesja, znacznik czasu). Aplikacja przy braku
   zasiegu odklada paczke i probuje ponownie, wiec ta sama probka potrafi
   przyjsc dwa razy - i lepiej, zeby przyszla dwa razy, niz wcale.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import closing
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

DB_PATH = os.environ.get("TELEMETRY_DB", "/data/recordings.db")
TOKEN = os.environ.get("TELEMETRY_TOKEN", "")

app = FastAPI(
    title="XC60 telemetry",
    description="Nagrania metryk z aplikacji pokladowej.",
    version="1.0.0",
)


# --- baza --------------------------------------------------------------------

def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    # WAL: zapis z auta nie blokuje odczytu z przegladarki.
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS samples (
                session   TEXT    NOT NULL,
                epoch_ms  INTEGER NOT NULL,
                payload   TEXT    NOT NULL,
                PRIMARY KEY (session, epoch_ms)
            )
            """
        )
        connection.commit()


init_db()


# --- autoryzacja -------------------------------------------------------------

def require_token(request: Request) -> None:
    if not TOKEN:
        raise HTTPException(500, "TELEMETRY_TOKEN nie jest ustawiony po stronie serwera")
    header = request.headers.get("authorization", "")
    if header != f"Bearer {TOKEN}":
        raise HTTPException(401, "Zly token")


# Bez kropki: inaczej ".csv" wpada do {session} jako czesc nazwy sesji.
SESSION = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")


# --- zapis -------------------------------------------------------------------

class SampleBatch(BaseModel):
    samples: list[dict[str, Any]]


class BatchAck(BaseModel):
    stored: int
    total: int


@app.post("/v1/recordings/{session}/samples", dependencies=[Depends(require_token)])
def upload(batch: SampleBatch, session: str = SESSION) -> BatchAck:
    rows = []
    for sample in batch.samples:
        epoch = sample.get("t")
        if not isinstance(epoch, int):
            raise HTTPException(422, "Probka bez pola 't' (czas UNIX w ms)")
        rows.append((session, epoch, json.dumps(sample, separators=(",", ":"))))

    with closing(connect()) as connection:
        # INSERT OR REPLACE, bo ponowiona paczka to nie blad - patrz naglowek.
        connection.executemany(
            "INSERT OR REPLACE INTO samples (session, epoch_ms, payload) VALUES (?, ?, ?)",
            rows,
        )
        connection.commit()
        total = connection.execute(
            "SELECT COUNT(*) FROM samples WHERE session = ?", (session,)
        ).fetchone()[0]

    return BatchAck(stored=len(rows), total=total)


# --- odczyt ------------------------------------------------------------------

@app.get("/v1/recordings", dependencies=[Depends(require_token)])
def list_recordings() -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT session,
                   COUNT(*)      AS samples,
                   MIN(epoch_ms) AS first_ms,
                   MAX(epoch_ms) AS last_ms
            FROM samples
            GROUP BY session
            ORDER BY first_ms DESC
            """
        ).fetchall()
    return [
        {
            "session": row["session"],
            "samples": row["samples"],
            "first_ms": row["first_ms"],
            "last_ms": row["last_ms"],
            "duration_s": round((row["last_ms"] - row["first_ms"]) / 1000, 1),
        }
        for row in rows
    ]


@app.get("/v1/recordings/{session}.csv", dependencies=[Depends(require_token)])
def read_recording_csv(session: str = SESSION) -> StreamingResponse:
    """CSV, bo do strojenia progow i tak konczy sie na arkuszu albo wykresie.

    Kolumny powstaja z SUMY kluczy faktycznie zapisanych probek, w kolejnosci
    pierwszego wystapienia. Dzieki temu dolozenie metryki w aplikacji nie
    wymaga niczego po stronie serwera.
    """
    payloads = list(_payloads(session))
    if not payloads:
        raise HTTPException(404, "Nie ma takiego nagrania")

    columns: list[str] = []
    for payload in payloads:
        for key in payload:
            if key not in columns:
                columns.append(key)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(payloads)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session}.csv"'},
    )


@app.get("/v1/recordings/{session}", dependencies=[Depends(require_token)])
def read_recording(session: str = SESSION) -> list[dict[str, Any]]:
    return list(_payloads(session))


@app.delete("/v1/recordings/{session}", dependencies=[Depends(require_token)])
def delete_recording(session: str = SESSION) -> dict[str, int]:
    with closing(connect()) as connection:
        cursor = connection.execute("DELETE FROM samples WHERE session = ?", (session,))
        connection.commit()
    return {"deleted": cursor.rowcount}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Bez tokenu -- sluzy tylko do sprawdzenia, czy kontener zyje."""
    return {"status": "ok"}


def _payloads(session: str) -> Iterator[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT payload FROM samples WHERE session = ? ORDER BY epoch_ms",
            (session,),
        ).fetchall()
    for row in rows:
        yield json.loads(row["payload"])
