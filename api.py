import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import festival as fz

WEB = Path(__file__).parent / "web"


class PerformanceIn(BaseModel):
    kind: str
    title: str
    venue: str
    start: str
    duration_minutes: int
    description: str = ""
    artist: str | None = None
    min_age: int = 0
    host: str | None = None
    acts: list[str] = []
    teacher: str | None = None
    max_participants: int | None = None
    participants: list[str] = []


class ArtistIn(BaseModel):
    name: str
    bio: str = ""
    photo_url: str = ""


class ParticipantIn(BaseModel):
    name: str


def create_app(path=None):
    path = path or os.environ.get("FESTIVAL_DATA") or fz.DATA_FILE
    app = FastAPI(title="Deauville Festival du Rire")
    cache = { }

    def fest():
        if "f" not in cache:
            cache["f"] = fz.load(path)
        return cache["f"]

    def save():
        try:
            fz.save( fest(), path )
        except fz.FestivalError:
            cache.clear()
            raise

    @app.exception_handler(fz.FestivalError)
    async def on_error(request, e):
        return JSONResponse({"detail": str(e)}, status_code=e.code)

    @app.get("/api/festival")
    def get_festival():
        return fest().info()

    @app.get("/api/venues")
    def get_venues():
        return [ v.to_dict() for v in fest().venues.values() ]

    @app.get("/api/artists")
    def get_artists():
        return [a.to_dict() for a in fest().sorted_artists()]

    @app.get("/api/artists/{slug}")
    def get_artist(slug: str):
        f = fest()
        shows = [f.perf_dict(p) for p in f.shows_of(slug)]
        return {**f.artist(slug).to_dict(), "performances": shows}

    @app.get("/api/programme")
    def get_programme(day: date | None = None, venue: str | None = None):
        f = fest()
        return [f.perf_dict(p) for p in f.programme(day, venue)]

    @app.get("/api/performances/{pid}")
    def get_performance(pid: str):
        f = fest()
        return f.perf_dict(f.performance(pid))

    @app.get("/api/now")
    def get_now(at: datetime | None = None):
        f = fest()
        at = (at or datetime.now()).replace(second=0, microsecond=0, tzinfo=None)
        playing, upcoming = f.now(at)
        return {
            "at": at.strftime(fz.FMT),
            "now_playing": [f.perf_dict(p) for p in playing],
            "up_next": [f.perf_dict(p) for p in upcoming],
        }

    @app.post("/api/artists", status_code=201)
    def post_artist(body: ArtistIn):
        a = fest().add_artist(body.model_dump())
        save()
        return a.to_dict()

    @app.post("/api/performances", status_code=201)
    def post_performance(body: PerformanceIn):
        f = fest()
        p = f.add_performance(body.model_dump())
        save()
        return f.perf_dict(p)

    @app.put("/api/performances/{pid}")
    def put_performance(pid: str, body: PerformanceIn):
        f = fest()
        p = f.replace_performance(pid, body.model_dump())
        save()
        return f.perf_dict(p)

    @app.delete("/api/performances/{pid}", status_code=204)
    def delete_performance(pid: str):
        fest().remove_performance(pid)
        save()
        return Response(status_code=204)

    @app.post("/api/performances/{pid}/participants", status_code=201)
    def post_participant(pid: str, body: ParticipantIn):
        f = fest()
        p = f.register(pid, body.name)
        save()
        return f.perf_dict(p)

    app.mount("/admin", StaticFiles(directory=WEB / "admin", html=True), name="admin")
    app.mount("/", StaticFiles(directory=WEB / "public", html=True), name="public")
    return app


app = create_app()
