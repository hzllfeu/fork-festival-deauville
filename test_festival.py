import json
import shutil

import pytest
from fastapi.testclient import TestClient

import api
import festival as fz
import main


@pytest.fixture
def data_file(tmp_path):
    p = tmp_path / "festival.json"
    shutil.copy(fz.DATA_FILE, p)
    return p


@pytest.fixture
def f(data_file):
    return fz.load(data_file)


@pytest.fixture
def client(data_file):
    return TestClient(api.create_app(data_file))


def solo(**changes):
    x = {
        "kind": "solo",
        "title": "Test",
        "venue": "la-cabane",
        "start": "2027-06-10T18:00",
        "duration_minutes": 60,
        "artist": "nora-lebrun",
        "min_age": 0,}
    x.update( changes )
    return x


def test_slug():
    assert fz.slugify("Théâtre des Planches") == "theatre-des-planches"
    assert fz.slugify("Élodie  Marchal !") == "elodie-marchal"


def test_load(f):
    assert len(f.venues) == 4 and len(f.artists) == 12 and len( f.performances ) == 23
    assert f.sorted_artists()[0].name == "Élodie Marchal"
    assert "le-kiosque-2027-06-12-0100" in f.performances


def test_dayends_at_six(f):
    assert f.performance("le-kiosque-2027-06-12-0100").day().isoformat() == "2027-06-11"
    assert len(f.programme(fz.parse_day("2027-06-11", "d"))) == 7


def test_names_stripped(f):
    assert f.add_artist({"name": "  Zoé Test  "}).name == "Zoé Test"
    with pytest.raises(fz.Invalid):
        f.add_artist({"name": "   "})
    with pytest.raises(fz.Conflict):
        f.add_artist({"name": "zoe test"})


def test_venue_busy(f):
    with pytest.raises(fz.Conflict, match="Le Kiosque is busy with After Hours"):
        f.add_performance(solo(venue="le-kiosque", start="2027-06-12T02:15"))
    f.add_performance(solo(venue="le-kiosque", start="2027-06-12T02:30"))


def test_artist_busy(f):
    with pytest.raises(fz.Conflict, match="Nora Lebrun is busy"):
        f.add_performance(solo(start="2027-06-11T19:30"))
    f.add_performance(solo(start="2027-06-11T19:45"))


def test_outside_festival(f):
    with pytest.raises(fz.Conflict):
        f.add_performance(solo(start="2027-06-14T10:00"))
    with pytest.raises(fz.Conflict):
        f.add_performance(solo(start="2027-06-10T05:00"))
    f.add_performance(solo(start="2027-06-14T05:00", duration_minutes=30))


def test_values(f):
    with pytest.raises(fz.Invalid):
        f.add_performance(solo(duration_minutes=0))
    with pytest.raises(fz.Invalid):
        f.add_performance(solo(duration_minutes=361))
    with pytest.raises(fz.Invalid):
        f.add_performance(solo(min_age=19))
    with pytest.raises(fz.Invalid):
        f.add_performance(solo(title=" "))
    with pytest.raises(fz.NotFound):
        f.add_performance(solo(artist="nobody"))
    with pytest.raises(fz.NotFound):
        f.add_performance(solo(venue="nowhere"))


def test_lineup(f):
    x = {**solo(), "kind": "lineup", "host": "paul-kerbrat", "duration_minutes": 35}
    with pytest.raises(fz.Invalid, match="36 minutes"):
        f.add_performance({**x, "acts": ["nora-lebrun", "max-pellerin", "hugo-lemaire"]})
    with pytest.raises(fz.Invalid):
        f.add_performance({**x, "acts": ["nora-lebrun"]} )
    with pytest.raises(fz.Invalid):
        f.add_performance({**x, "acts": ["nora-lebrun", "nora-lebrun"]})
    with pytest.raises(fz.Invalid):
        f.add_performance({**x, "acts": ["nora-lebrun", "paul-kerbrat"]})
    p = f.add_performance({**x, "duration_minutes": 36, "acts": ["nora-lebrun", "max-pellerin", "hugo-lemaire"]})
    assert f.perf_dict( p)["artists"][0]["slug"] == "paul-kerbrat"


def test_workshop(f):
    x = {**solo(), "kind": "workshop", "teacher": "ines-moreau", "max_participants": 2}
    p = f.add_performance(x)
    f.register(p.id(), "Camille R.")
    with pytest.raises(fz.Conflict, match="already registered"):
        f.register(p.id(), " camille r. ")
    f.register(p.id(), "Lou")
    with pytest.raises(fz.Conflict, match="full"):
        f.register(p.id(), "Max")
    with pytest.raises(fz.Invalid):
        f.register("le-kiosque-2027-06-12-0100", "Max")
    assert f.perf_dict(f.add_performance({**x, "start": "2027-06-11T08:00", "max_participants": 100}))["capacity"] == 40


def test_move_is_atomic(f):
    i = "le-kiosque-2027-06-12-0100"
    x = f.performance(i).raw()
    with pytest.raises(fz.Conflict):
        f.replace_performance(i, {**x, "start": "2027-06-11T23:45"})
    assert i in f.performances
    p = f.replace_performance(i, {**x, "venue": "la-cabane"})
    assert p.id() == "la-cabane-2027-06-12-0100" and i not in f.performances


def test_save_round_trip(f, data_file):
    f.add_artist({"name": "Zoé"})
    fz.save(f, data_file)
    assert "zoe" in fz.load(data_file).artists


def test_broken_files(data_file):
    data_file.write_text("{oops", encoding="utf-8")
    with pytest.raises(fz.StorageError, match="not valid JSON"):
        fz.load(data_file)
    x = json.loads(fz.DATA_FILE.read_text(encoding="utf-8"))
    x["performances"][1]["start"] = "2027-06-10T21:30"
    x["performances"][1]["venue"] = "grand-casino"
    data_file.write_text(json.dumps(x), encoding="utf-8")
    with pytest.raises(fz.StorageError, match="Grand Casino is busy"):
        fz.load(data_file)
    with pytest.raises(fz.StorageError, match="Cannot read"):
        fz.load(data_file.parent / "missing.json")


def test_cli(data_file, capsys):
    assert main.main(["--data", str(data_file), "day", "2027-06-11"]) == 0
    assert "After Hours" in capsys.readouterr().out
    assert main.main(["--data", str(data_file), "now", "--at", "2027-06-11T21:00"]) == 0
    assert "Tall Tales" in capsys.readouterr().out
    data_file.write_text("[]", encoding="utf-8")
    assert main.main(["--data", str(data_file), "artists"]) == 1


def test_api_read(client):
    assert client.get("/api/festival").json()["days"][0] == "2027-06-10"
    assert client.get("/api/venues").json()[0]["slug"] == "grand-casino"
    assert len(client.get("/api/programme?day=2027-06-11").json()) == 7
    assert client.get("/api/programme?day=June 11").status_code == 422
    assert client.get("/api/artists/nobody").status_code == 404
    assert len(client.get("/api/artists/nora-lebrun").json()["performances"]) == 4
    r = client.get("/api/now?at=2027-06-11T21:00").json()
    assert [p["title"] for p in r["now_playing"]] == ["Tall Tales"]
    assert len(r["up_next"]) == 3
    assert client.get("/").status_code == 200 and client.get("/admin/").status_code == 200


def test_api_write(client, data_file):
    assert client.post("/api/artists", json={"name": "Zoé"}).status_code == 201
    assert client.post("/api/artists", json={"name": "zoe"}).status_code == 409
    r = client.post("/api/performances", json=solo())
    assert r.status_code == 201
    i = r.json()["id"]
    assert client.post("/api/performances", json=solo(duration_minutes=0)).status_code == 422
    r =  client.put(f"/api/performances/{i}", json=solo(start="2027-06-10T17:00"))
    assert r.json()["id"] == "la-cabane-2027-06-10-1700"
    assert client.post(f"/api/performances/{r.json()['id']}/participants", json={"name": "A"}).status_code == 422
    r = client.post("/api/performances/la-cabane-2027-06-13-1030/participants", json={"name": "Max"})
    assert r.status_code == 201 and r.json()["places_left"] == 11
    assert client.delete("/api/performances/la-cabane-2027-06-10-1700").status_code == 204
    assert client.delete("/api/performances/la-cabane-2027-06-10-1700").status_code == 404
    x = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(x["performances"]) == 23 and len(x["artists"]) ==  13


def test_api_broken_file(data_file):
    data_file.write_text("{", encoding="utf-8")
    r = TestClient(api.create_app(data_file)).get("/api/festival")
    assert r.status_code == 500 and "not valid JSON" in r.json()["detail"]
