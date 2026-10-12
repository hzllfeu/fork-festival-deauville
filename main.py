import argparse
import os
import sys
from datetime import date, datetime

import festival as fz


def line(f, p):
    venue = f.venues[p.venue].name
    return f"{p.start:%H:%M}-{p.end():%H:%M}   {venue:<22} {p.title} ({p.kind}), {p.summary(f)}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="festival", description="Deauville Festival du Rire")
    parser.add_argument("--data", default=str(fz.DATA_FILE), help="data file (default: data/festival.json)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cmd = sub.add_parser("day", help="programme of one festival day")
    cmd.add_argument("day", type=date.fromisoformat, help="e.g. 2027-06-11"
                     )
    sub.add_parser("artists", help="artists and their number of shows")

    cmd = sub.add_parser("now", help="on stage at a moment, and the next 3")

    cmd.add_argument("--at", type=datetime.fromisoformat, help="e.g. 2027-06-11T21:00")

    cmd = sub.add_parser("serve", help="start the web server")
    cmd.add_argument("--port", type=int, default=8000)
    
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        os.environ["FESTIVAL_DATA"] = args.data
        uvicorn.run("api:app", port=args.port)
        return 0

    try:
        f = fz.load(args.data)
    except fz.FestivalError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.cmd == "day":
        if not f.first_day <= args.day <= f.last_day:
            print(
                f"Error: {args.day} is not a festival day ({f.first_day} to {f.last_day})",
                file=sys.stderr,)
            return 1
        shows = f.programme(args.day)
        print(f"{args.day:%A %d %B %Y}: {len(shows)} performnce(s)")
        for p in shows:
            print("  " + line(f, p))
    elif args.cmd == "artists":
        for a in f.sorted_artists():
            print(f"{a.name:<20} {len(f.shows_of(a.slug))} show(s)")
    elif args.cmd == "now":
        at = (args.at or datetime.now()).replace(second=0, microsecond=0, tzinfo=None)
        playing, upcoming = f.now(at)
        print(f"At {at:%Y-%m-%d %H:%M}")
        print("On stage:" if playing else "On stage: nothing")
        for p in playing:
            print("  " + line(f, p))
        print("Up next:" if upcoming else "Up next: nothing, the festival is over")
        for p in upcoming:
            print(f"  {p.start:%Y-%m-%d} " + line(f, p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
