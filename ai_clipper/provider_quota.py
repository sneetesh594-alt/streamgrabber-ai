"""Share provider limits across credentials and suspend the current worker at a call boundary."""
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta, time as midnight
from zoneinfo import ZoneInfo

GROQ_KEYS = tuple(f"GROQ_API_KEY_{i}" for i in range(1,5))


def database():
    folder = Path(os.getenv("STREAMGRABBER_STATE_DIR", "output/studio-state"))
    folder.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(folder/"provider-limits.sqlite3",timeout=15,isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS gates(provider TEXT PRIMARY KEY, until REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS calls(at REAL, seconds INTEGER)")
    db.execute("CREATE INDEX IF NOT EXISTS calls_at ON calls(at)")
    return db


def stop_until(provider, deadline):
    with closing(database()) as db:
        db.execute("INSERT INTO gates VALUES (?,?) ON CONFLICT(provider) DO UPDATE SET until=max(until,excluded.until)",(provider,deadline))


def pending():
    with closing(database()) as db:
        row=db.execute("SELECT provider,until FROM gates WHERE until>? ORDER BY until DESC LIMIT 1",(time.time(),)).fetchone()
    return row


def wait_for_reset(report):
    while hold := pending():
        provider, deadline=hold
        report(provider,deadline)
        time.sleep(max(.05,min(30,deadline-time.time())))


def reserve_audio(seconds):
    now=time.time()
    with closing(database()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM calls WHERE at<=?",(now-86400,))
        hold=db.execute("SELECT max(until) FROM gates WHERE until>?",(now,)).fetchone()[0]
        if hold:
            db.commit()
            return False
        # One shared rolling ledger per worker installation, including distinct keys.
        planned_reset=0.
        for period,limit,cost,by_audio in [(60,20,1,False),(86400,2000,1,False),
                (3600,7200,seconds,True),(86400,28800,seconds,True)]:
            data=db.execute("SELECT at,seconds FROM calls WHERE at>? ORDER BY at",(now-period,)).fetchall()
            used=sum(r[1] if by_audio else 1 for r in data)
            guard=limit-math.ceil(limit*.01)
            if used+cost==guard:
                planned_reset=max(planned_reset,(data[0][0] if data else now)+period+.1)
            if used+cost>guard:
                for at,n in data:
                    used-=n if by_audio else 1
                    if used+cost<=guard:
                        break
                db.execute("INSERT OR REPLACE INTO gates VALUES ('Groq',?)",(at+period+.1,))
                db.commit()
                return False
        db.execute("INSERT INTO calls VALUES (?,?)",(now,seconds))
        if planned_reset:
            db.execute("INSERT OR REPLACE INTO gates VALUES ('Groq',?)",(planned_reset,))
        db.commit()
        return True


def reset_seconds(raw, fallback):
    raw=str(raw or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?",raw):
        return max(1,float(raw))
    matches=re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)",raw)
    if not matches or "".join(n+u for n,u in matches)!=raw:
        return fallback
    return max(1,sum(float(n)*{"ms":.001,"s":1,"m":60,"h":3600,"d":86400}[u] for n,u in matches))


def observe_groq(headers, status, next_tokens=0):
    waits=[]
    for kind,fallback in (("requests",86400),("tokens",60)):
        try:
            limit=int(headers.get("x-ratelimit-limit-"+kind))
            left=int(headers.get("x-ratelimit-remaining-"+kind))
        except (ValueError,TypeError):
            continue
        projected = next_tokens if kind == "tokens" else 0
        if limit>0 and left-projected<=math.ceil(limit*.01):
            waits.append(reset_seconds(headers.get("x-ratelimit-reset-"+kind),fallback))
    if status==429:
        waits.append(reset_seconds(headers.get("retry-after"),60))
    if waits:
        stop_until("Groq",time.time()+max(waits))


def gemini_deadline():
    now=datetime.now(ZoneInfo("America/Los_Angeles"))
    return datetime.combine(now.date()+timedelta(days=1),midnight.min,now.tzinfo).timestamp()


def audio_usage():
    with closing(database()) as db:
        calls,seconds=db.execute("SELECT count(*), coalesce(sum(seconds),0) FROM calls WHERE at>?",(time.time()-86400,)).fetchone()
    return {"groq_requests":calls,"groq_audio_seconds":seconds}
