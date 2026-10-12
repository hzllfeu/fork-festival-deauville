import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "festival.json"
GAP = timedelta( minutes=30)
DAY_END = timedelta(hours=6)
FMT = "%Y-%m-%dT%H:%M"


class FestivalError(Exception):
    code = 400

class NotFound(FestivalError):
    code = 404


class Conflict(FestivalError):
    code = 409

class Invalid(FestivalError):
    code = 422


class StorageError(FestivalError):
    code = 500

def clean_name(x, what="name"):
    if not isinstance(x, str) or not x.strip():
        raise Invalid(f"{what.capitalize()} required")
    return x.strip()


def slugify(x):
    s = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip( "-" )
    if not s:
        raise Invalid(f'"{x}" gives an empty identifier: use letters or digits')
    return s


def check_int(x, what, lo, hi=None):
    if isinstance(x, bool) or not isinstance(x, int):
        raise Invalid(f"{what.capitalize()} must be a whole number")
    if x < lo or (hi is not None and x > hi):
        if hi is None:
            raise Invalid(f"{what.capitalize()} must be at least {lo}, got {x}")
        raise Invalid(f"{what.capitalize()} must be between {lo} and {hi}, got {x}")
    
    return x


def parse_start(x):

    if not isinstance(x, datetime):

        try:
            x = datetime.fromisoformat(x)
        except (TypeError, ValueError):
            raise Invalid(f'"{x}" is not a valid start') from None
        
    return x.replace(second=0, microsecond=0, tzinfo=None)


def parse_day(x, what):
    if isinstance(x, date):
        
        return x
    try:
        return date.fromisoformat(x)
    except (TypeError, ValueError):
        raise Invalid(f'The {what} "{x}" is not a valid date') from None


def check_ref(x, what):
    if not isinstance(x, str) or not x.strip():
        raise Invalid(f"{what.capitalize()} required")
    return x.strip()


def slot(p):
    return f"{p.start:%Y-%m-%d %H:%M}-{p.end():%H:%M}"


class Venue:
    def __init__(self, data):
        self.name = clean_name( data.get("name"), "venue name" )
        self.slug = slugify( self.name )
        self.capacity = check_int( data.get("capacity"), "number of seats", 1 )
        self.address = clean_name( data.get("address"), "address" )

    def raw(self):
        return {"name": self.name, "capacity": self.capacity, "address": self.address}

    def to_dict(self):

        return {"slug": self.slug, **self.raw()}


class Artist:
    def __init__(self, data):
        self.name = clean_name( data.get("name"), "artist name" )
        self.slug = slugify( self.name )
        self.bio = str( data.get("bio") or "" ).strip( )
        self.photo_url = str(data.get("photo_url") or "").strip( )

    def raw(self):
        return {"name": self.name, "bio": self.bio, "photo_url": self.photo_url}

    def to_dict(self):
        return {"slug": self.slug, **self.raw()}


class Performance:
    kind = ""

    def __init__(self, data):
        self.title = clean_name( data.get("title"), "title" )
        self.venue = check_ref( data.get("venue"), "venue" )
        self.start = parse_start( data.get("start") )
        self.duration = check_int(data.get("duration_minutes"), "duration in minutes", 1, 360 )
        desc = data.get("description") or ""
        if not isinstance(desc, str):
            raise Invalid("Description must be text")
        self.description = desc.strip( )

    def end(self):
        return self.start + timedelta( minutes = self.duration )


    def day(self):
        return (self.start - DAY_END).date()

    def id(self):
        return f"{self.venue}-{self.start:%Y-%m-%d-%H%M}"

    def on_stage(self):
        return [ ]

    def capacity(self, fest):
        return fest.venues[self.venue].capacity


    def summary(self, fest):
        return ""

    def extra(self, fest):
        return { }

    def raw(self):
        return {
            "kind": self.kind,
            "title": self.title,
            "venue": self.venue,
            "start": self.start.strftime(FMT),
            "duration_minutes": self.duration,
            "description": self.description,}


class Solo(Performance):
    kind = "solo"

    def __init__(self, data):
        super().__init__(data)
        self.artist = check_ref(data.get("artist"), "solo artist")
        self.min_age = check_int(data.get("min_age", 0), "minimum age", 0, 18)


    def on_stage(self):
        return [self.artist]

    def summary(self, fest):
        s = f"by {fest.artists[self.artist].name}"
        return s + (f", {self.min_age}+" if self.min_age else "")

    def extra(self, fest):
        return {"artist": self.artist, "min_age": self.min_age}

    def raw(self):
        return {**super().raw(), **self.extra(None)}


class Lineup(Performance):
    kind = "lineup"

    def __init__(self, data):
        super().__init__(data)
        self.host = check_ref(data.get("host"), "host")
        acts = data.get("acts")
        if not isinstance(acts, list) or len(acts) < 2:
            raise Invalid("Lineup needs at least 2 acts")
        
        self.acts = [check_ref(a, "act") for a in acts]

        for a in self.acts:
            if self.acts.count(a) > 1:
                raise Invalid(f"{a} appears twice in acts: one stage appearance each")
        if self.host in self.acts:
            raise Invalid(f"{self.host} hosts the lineup and is also listed as an act")
        n = len(self.acts)
        need = n * 10 + (n - 1) * 3
        if self.duration < need:
            raise Invalid(
                f"a lineup of {n} acts lasts at least {need} minutes "
                f"(10 per act 3 for the host between two acts) got {self.duration}"
            )

    def on_stage(self):
        return [self.host, *self.acts]

    def summary(self, fest):
        names = [fest.artists[a].name for a in self.acts]
        host = fest.artists[self.host].name
        return f"hosted by {host}, with {', '.join(names[:-1])} and {names[-1]}"

    def extra(self, fest):
        return {"host": self.host, "acts": list(self.acts)}

    def raw(self):
        return {**super().raw(), **self.extra(None)}


class Workshop(Performance):
    kind = "workshop"

    def __init__(self, data):
        super().__init__(data)
        self.teacher = check_ref(data.get("teacher"), "teacher")
        self.max_participants = check_int(
            data.get("max_participants"), "maximum number of participant", 1)

        names = data.get("participants") or []
        if not isinstance(names, list):
            raise Invalid("Participants must be a list of names")
        self.participants = []
        for n in names:
            self.participants.append(self.check_participant(n) )


    def check_participant(self, name):
        name = clean_name(name, "participant name")
        if name.casefold() in [p.casefold() for p in self.participants]:

            raise Conflict(f"{name} is already registered for {self.title}")
        return name

    def register(self, name, fest):
        name = self.check_participant(name)
        if len(self.participants) >= self.capacity(fest):
            raise Conflict(f"{self.title} is full: {self.capacity(fest)} places all taken")
        self.participants.append(name)

    def capacity(self, fest):
        return min(self.max_participants, fest.venues[self.venue].capacity)

    def on_stage(self):

        return [self.teacher]

    def summary(self, fest):
        teacher = fest.artists[self.teacher].name
        return f"with {teacher}, {len(self.participants)}/{self.capacity(fest)} registered"

    def extra(self, fest):
        return {
            "teacher": self.teacher,
            "max_participants": self.max_participants,
            "participants": list(self.participants),
            "places_left": self.capacity(fest) - len(self.participants),
        }

    def raw(self):
        return {
            **super().raw(),
            "teacher": self.teacher,
            "max_participants": self.max_participants,
            "participants": list(self.participants),}


KINDS = {"solo": Solo, "lineup": Lineup, "workshop": Workshop}


class Festival:
    def __init__(self, name, first_day, last_day):
        self.name = clean_name(name, "festival name")
        self.first_day = parse_day(first_day, "first day")
        self.last_day = parse_day(last_day, "last day")
        if self.last_day < self.first_day:
            raise Invalid("Last festival day is before first day")
        
        self.venues = {}
        self.artists = {}
        self.performances = {}

    def days(self):
        n = (self.last_day - self.first_day).days + 1

        return [self.first_day + timedelta(days=i) for i in range(n)]

    def add_venue(self, data):
        v = Venue(data)
        if v.slug in self.venues:
            raise Conflict(f"Venue already exists: {v.name}")
        
        self.venues[v.slug] = v
        return v

    def add_artist(self, data):
        a = Artist(data)
        if a.slug in self.artists:
            raise Conflict(f"Artist already exists: {self.artists[a.slug].name}")
        self.artists[a.slug] = a
        return a

    def build(self, data):
        if not isinstance(data, dict):
            raise Invalid("Performance must be an object with fields")
        cls = KINDS.get(data.get("kind"))
        if cls is None:
            raise Invalid(
                f'Unknown performance kind "{data.get("kind")}" use solo or lineup or workshop'
            )
        return cls(data)

    def check(self, p, skip=None):
        if p.venue not in self.venues:
            raise NotFound(f"Unknown venue: {p.venue}")
        for a in p.on_stage():
            if a not in self.artists:
                raise NotFound(f"Unknown artist: {a}")
        if not self.first_day <= p.day() <= self.last_day:
            raise Conflict(
                f"{p.title} starts on {p.start:%Y-%m-%d %H:%M}, outside the festival "
                f"({self.first_day} to {self.last_day}); festival day ends at 06:00")
        if isinstance(p, Workshop) and len(p.participants) > p.capacity(self):
            raise Conflict(
                f"{p.title} has {len(p.participants)} participants "
                f"but only {p.capacity(self)} places available"
            )
        for other in self.performances.values():
            if other.id() == skip:
                continue

            if not (p.start < other.end() + GAP and other.start < p.end() + GAP):
                continue
            where = self.venues[other.venue].name
            if other.venue == p.venue:
                raise Conflict(
                    f"{where} is busy with {other.title} ({slot(other)}). "
                    "Leave 30 minutes between two shows")
            
            for a in p.on_stage():
                if a in other.on_stage():
                    raise Conflict(
                        f"{self.artists[a].name} is busy with {other.title} at {where} "
                        f"({slot(other)}). Leave 30 minutes between 2 performances")
                    

    def add_performance(self, data):
        p = self.build(data)
        self.check(p)
        self.performances[p.id()] = p
        return p

    def replace_performance(self, pid, data):
        self.performance(pid)
        p = self.build(data)
        self.check(p, skip=pid)
        del self.performances[pid]
        self.performances[p.id()] = p
        return p

    def remove_performance(self, pid):
        self.performance(pid)
        del self.performances[pid]

    def register(self, pid, name):
        p = self.performance(pid)
        if not isinstance(p, Workshop):
            raise Invalid(f"{p.title} is not a workshop: no registration")
        p.register(name, self)
        return p

    def performance(self, pid):
        if pid not in self.performances:
            raise NotFound(f"Unknown performance: {pid}")
        
        return self.performances[pid]

    def artist(self, slug):
        if slug not in self.artists:
            raise NotFound(f"Unknown artist: {slug}")
        return self.artists[slug]

    def venue(self, slug):
        if slug not in self.venues:
            raise NotFound(f"Unknown venue: {slug}" )
        return self.venues[slug]

    def programme(self, day=None, venue=None):
        if venue is not None:
            self.venue(venue)

        res = [
            p
            for p in self.performances.values()
            if (day is None or p.day() == day) and (venue is None or p.venue == venue)]

        ordered = []
        for performance in res:
            venue_name = self.venues[performance.venue].name
            ordered.append(((performance.start, venue_name), performance))
        ordered.sort()
        return [performance for _, performance in ordered]

    def sorted_artists(self):
        return [self.artists[s] for s in sorted(self.artists)]

    def shows_of(self, slug):
        self.artist(slug)

        return [p for p in self.programme() if slug in p.on_stage()]

    def now(self, at):
        all_ = self.programme()
        playing = [p for p in all_ if p.start <= at < p.end()]
        upcoming = [p for p in all_ if p.start > at][:3]
        return playing, upcoming

    def perf_dict(self, p):
        return {
            "id": p.id(),
            "kind": p.kind,
            "title": p.title,
            "venue": p.venue,
            "venue_name": self.venues[p.venue].name,
            "start": p.start.strftime(FMT),
            "end": p.end().strftime(FMT),
            "duration_minutes": p.duration,
            "festival_day": p.day().isoformat(),
            "description": p.description,
            "summary": p.summary(self),
            "capacity": p.capacity(self),
            "artists": [{"slug": a, "name": self.artists[a].name} for a in p.on_stage()],
            **p.extra(self),
        }

    def info(self):
        return {
            "name": self.name,
            "first_day": self.first_day.isoformat(),
            "last_day": self.last_day.isoformat(),
            "days": [d.isoformat() for d in self.days()],
        }

    def raw(self):
        return {
            "name": self.name,
            "first_day": self.first_day.isoformat(),
            "last_day": self.last_day.isoformat(),
            "venues": [v.raw() for v in self.venues.values()],
            "artists": [a.raw() for a in self.sorted_artists()],
            "performances": [p.raw() for p in self.programme()],
        }


def load(path=DATA_FILE):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise StorageError(f"Cannot read data file {path}: {e.strerror}") from None
    try:
        data = json.loads(text)

    except json.JSONDecodeError as e:
        raise StorageError(
            f"Data file {path}: not valid JSON (line {e.lineno}, column {e.colno})"
        ) from None
    where = "festival"
    try:
        fest = Festival(data.get("name"), data.get("first_day"), data.get("last_day"))
        for item in data.get("venues") or []:
            where = f"venue {item.get('name')!r}"
            fest.add_venue(item)
        for item in data.get("artists") or []:
            where = f"artist {item.get('name')!r}"
            fest.add_artist(item)
        for item in data.get("performances") or []:
            where = f"performance {item.get('title')!r} ({item.get('start')})"
            fest.add_performance(item)
    except FestivalError as e:
        raise StorageError(f"Data file {path} broken, {where}: {e}") from None
    except (AttributeError, TypeError):
        raise StorageError(
            f"Data file {path} broken, {where}: unexpected shape"
        ) from None
    return fest


def save(fest, path=DATA_FILE):
    path = Path(path)
    tmp = path.with_suffix( ".tmp" )
    try:
        tmp.write_text(
            json.dumps(fest.raw(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, path)
    except OSError as e:
        raise StorageError(f"Cannot write data file {path}: {e.strerror}") from None
