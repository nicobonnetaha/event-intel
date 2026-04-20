import asyncio
import csv
import io
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(__file__))

from database import get_db, init_db
from models import Event, Participant, Setting, Workspace
from scorer import score_participant
from scrapers.luma import fetch_event_and_guests, fetch_event_metadata, extract_event_ids_from_cookie, parse_guest
from scrapers.enricher import enrich_participant


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Event Intel", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    url: str
    auth_token: Optional[str] = None


class ParticipantManual(BaseModel):
    name: str
    company: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    telegram_handle: Optional[str] = None
    bio: Optional[str] = None


# ── Workspace helpers ─────────────────────────────────────────────────────────

def _ws_key(workspace_id: int, key: str) -> str:
    return f"ws_{workspace_id}:{key}"


def get_workspace_id(x_workspace_id: Optional[str] = Header(None)) -> Optional[int]:
    if not x_workspace_id:
        return None
    try:
        return int(x_workspace_id)
    except (ValueError, TypeError):
        return None


# ── Workspace endpoints ───────────────────────────────────────────────────────

@app.post("/api/workspaces/auth")
def workspace_auth(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Create or join a workspace."""
    name = (payload.get("name") or "").strip()
    pin  = (payload.get("pin")  or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom requis")

    ws = db.query(Workspace).filter(Workspace.name.ilike(name)).first()
    if ws:
        if ws.pin and ws.pin != pin:
            raise HTTPException(status_code=401, detail="PIN incorrect")
        return {"id": ws.id, "name": ws.name}
    else:
        ws = Workspace(name=name, pin=pin or None)
        db.add(ws)
        db.commit()
        db.refresh(ws)
        return {"id": ws.id, "name": ws.name}


@app.get("/api/workspaces")
def list_workspaces(db: Session = Depends(get_db)):
    workspaces = db.query(Workspace).order_by(Workspace.name).all()
    return [{"id": w.id, "name": w.name, "has_pin": bool(w.pin)} for w in workspaces]


@app.patch("/api/workspaces/{workspace_id}")
def rename_workspace(workspace_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace introuvable")
    new_name = (payload.get("name") or "").strip()
    new_pin  = payload.get("pin")   # None = don't change, "" = remove pin
    if new_name:
        existing = db.query(Workspace).filter(
            Workspace.name.ilike(new_name), Workspace.id != workspace_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Ce nom est déjà pris")
        ws.name = new_name
    if new_pin is not None:
        ws.pin = new_pin.strip() or None
    db.commit()
    return {"id": ws.id, "name": ws.name, "has_pin": bool(ws.pin)}


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: int, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace introuvable")
    # Delete all events + participants in this workspace
    events = db.query(Event).filter(Event.workspace_id == workspace_id).all()
    for e in events:
        db.query(Participant).filter(Participant.event_id == e.id).delete()
    db.query(Event).filter(Event.workspace_id == workspace_id).delete()
    # Delete workspace settings
    db.query(Setting).filter(Setting.key.like(f"ws_{workspace_id}:%")).delete(synchronize_session=False)
    db.delete(ws)
    db.commit()
    return {"ok": True}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings/luma-token")
def get_luma_token(
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    key = _ws_key(workspace_id, "luma_token") if workspace_id else "luma_token"
    row = db.query(Setting).filter(Setting.key == key).first()
    return {"connected": bool(row and row.value)}


@app.post("/api/settings/luma-token")
def save_luma_token(
    payload: dict = Body(...),
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token vide")
    key = _ws_key(workspace_id, "luma_token") if workspace_id else "luma_token"
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = token
    else:
        db.add(Setting(key=key, value=token))
    db.commit()
    return {"ok": True}


@app.delete("/api/settings/luma-token")
def delete_luma_token(
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    key = _ws_key(workspace_id, "luma_token") if workspace_id else "luma_token"
    db.query(Setting).filter(Setting.key == key).delete()
    db.commit()
    return {"ok": True}


@app.get("/api/luma/my-events")
async def get_my_luma_events(
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    key = _ws_key(workspace_id, "luma_token") if workspace_id else "luma_token"
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row or not row.value:
        raise HTTPException(status_code=400, detail="Token Luma non configuré")

    token = row.value
    event_ids = extract_event_ids_from_cookie(token)
    if not event_ids:
        return {"events": [], "hint": "no_ids_in_cookie"}

    semaphore = asyncio.Semaphore(10)

    async def fetch_one(eid):
        async with semaphore:
            meta = await fetch_event_metadata(eid, token)
            if not meta:
                return None
            existing = db.query(Event).filter(
                Event.luma_id == meta["luma_id"],
                Event.workspace_id == workspace_id,
            ).first()
            meta["already_imported"] = bool(existing)
            meta["luma_url"] = f"https://lu.ma/{meta['url']}" if meta.get("url") else ""
            return meta

    results = await asyncio.gather(*[fetch_one(eid) for eid in event_ids])
    # Keep any event that has a name — don't filter on approval_status since
    # guest_data is absent when the user isn't the organizer, giving "unknown".
    events = [r for r in results if r and r.get("name")]

    from datetime import datetime, timezone

    def sort_key(e):
        try:
            return datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    future = sorted([e for e in events if sort_key(e) >= now], key=sort_key)
    past   = sorted([e for e in events if sort_key(e) <  now], key=sort_key, reverse=True)
    return {"events": future + past}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
def get_dashboard(
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    events_q = db.query(Event)
    if workspace_id:
        events_q = events_q.filter(Event.workspace_id == workspace_id)
    events = events_q.all()
    event_ids = [e.id for e in events]

    participants = (
        db.query(Participant).filter(Participant.event_id.in_(event_ids)).all()
        if event_ids else []
    )

    # ── Stats ──
    high   = sum(1 for p in participants if p.score_label == "Haute priorité")
    medium = sum(1 for p in participants if p.score_label == "Priorité moyenne")
    low    = sum(1 for p in participants if p.score_label == "Faible priorité")

    # ── Upcoming events (sorted by date asc, future only) ──
    now = datetime.now(timezone.utc)
    def _dt(e):
        try:
            return datetime.fromisoformat(e.date.replace("Z", "+00:00"))
        except Exception:
            return None

    upcoming = sorted(
        [e for e in events if _dt(e) and _dt(e) >= now],
        key=lambda e: _dt(e)
    )[:5]

    # Count high-priority per event
    from collections import defaultdict
    hp_by_event = defaultdict(int)
    for p in participants:
        if p.score_label == "Haute priorité":
            hp_by_event[p.event_id] += 1

    upcoming_out = []
    for e in upcoming:
        upcoming_out.append({
            "id": e.id,
            "name": e.name,
            "date": e.date,
            "location": e.location,
            "participant_count": e.participant_count or 0,
            "high_priority_count": hp_by_event[e.id],
        })

    # ── Top contacts (top 8 by score across all events) ──
    event_name_map = {e.id: e.name for e in events}
    top = sorted(participants, key=lambda p: p.score or 0, reverse=True)[:8]
    top_out = []
    for p in top:
        top_out.append({
            "id": p.id,
            "name": p.name,
            "company": p.company,
            "job_title": p.job_title,
            "score": p.score,
            "score_label": p.score_label,
            "avatar_url": p.avatar_url,
            "linkedin_url": p.linkedin_url,
            "event_id": p.event_id,
            "event_name": event_name_map.get(p.event_id, ""),
        })

    return {
        "stats": {
            "total_events": len(events),
            "total_participants": len(participants),
            "high_priority": high,
            "medium_priority": medium,
            "low_priority": low,
            "enriched": sum(1 for p in participants if p.enriched),
        },
        "upcoming_events": upcoming_out,
        "top_contacts": top_out,
    }


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Events ────────────────────────────────────────────────────────────────────

@app.get("/api/events")
def list_events(
    sort: str = "date_desc",
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    q = db.query(Event)
    if workspace_id:
        q = q.filter(Event.workspace_id == workspace_id)
    if sort == "date_asc":
        q = q.order_by(Event.date.asc().nullslast())
    else:
        q = q.order_by(Event.date.desc().nullslast())
    return [_event_dict(e) for e in q.all()]


@app.post("/api/events/import-luma")
async def import_from_luma(
    payload: EventCreate,
    background_tasks: BackgroundTasks,
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    token = payload.auth_token or ""
    if not token.strip():
        key = _ws_key(workspace_id, "luma_token") if workspace_id else "luma_token"
        row = db.query(Setting).filter(Setting.key == key).first()
        token = row.value if row else ""
    if not token.strip():
        raise HTTPException(
            status_code=400,
            detail="Aucun token Luma configuré. Connecte ton compte Luma d'abord."
        )
    try:
        data = await fetch_event_and_guests(payload.url, token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event = db.query(Event).filter(
        Event.luma_id == data["luma_id"],
        Event.workspace_id == workspace_id,
    ).first()
    if not event:
        event = Event(
            workspace_id=workspace_id,
            luma_id=data["luma_id"],
            name=data["name"],
            url=payload.url,
            date=data.get("date", ""),
            location=data.get("location", ""),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

    guests = data.get("guests", [])
    added = 0
    for raw in guests:
        parsed = parse_guest(raw)
        if not parsed.get("name"):
            continue
        existing = db.query(Participant).filter(
            Participant.event_id == event.id,
            Participant.luma_user_id == parsed.get("luma_user_id"),
        ).first()
        if existing:
            continue
        score, label, reason = score_participant(
            parsed["name"], parsed.get("company"), parsed.get("job_title"),
            parsed.get("bio"), None,
        )
        p = Participant(event_id=event.id, score=score, score_label=label, score_reason=reason,
                        **{k: v for k, v in parsed.items()})
        db.add(p)
        added += 1

    event.participant_count = db.query(Participant).filter(Participant.event_id == event.id).count()
    db.commit()
    return {"event": _event_dict(event), "imported": added}


@app.post("/api/events/create-manual")
def create_manual_event(
    name: str = Form(...),
    url: str = Form(""),
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    event = Event(name=name, url=url, workspace_id=workspace_id)
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_dict(event)


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.query(Participant).filter(Participant.event_id == event_id).delete()
    db.delete(event)
    db.commit()
    return {"ok": True}


# ── Participants ──────────────────────────────────────────────────────────────

@app.get("/api/events/{event_id}/participants")
def list_participants(
    event_id: int,
    search: str = "",
    priority: str = "",
    db: Session = Depends(get_db),
):
    q = db.query(Participant).filter(Participant.event_id == event_id)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(
            (Participant.name.ilike(like))
            | (Participant.company.ilike(like))
            | (Participant.job_title.ilike(like))
        )
    if priority:
        q = q.filter(Participant.score_label == priority)
    return [_participant_dict(p) for p in q.order_by(Participant.score.desc()).all()]


@app.post("/api/events/{event_id}/participants")
def add_participant(
    event_id: int,
    payload: ParticipantManual,
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    score, label, reason = score_participant(
        payload.name, payload.company, payload.job_title, payload.bio, None
    )
    p = Participant(event_id=event_id, score=score, score_label=label, score_reason=reason,
                    **payload.model_dump())
    db.add(p)
    event.participant_count = (event.participant_count or 0) + 1
    db.commit()
    db.refresh(p)
    return _participant_dict(p)


@app.post("/api/events/{event_id}/import-csv")
async def import_csv(
    event_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    added = 0
    for row in reader:
        name = row.get("name") or row.get("Name") or row.get("nom") or ""
        if not name.strip():
            continue
        company   = row.get("company") or row.get("Company") or row.get("société") or None
        job_title = row.get("job_title") or row.get("title") or row.get("Job Title") or row.get("poste") or None
        email     = row.get("email") or row.get("Email") or None
        linkedin  = row.get("linkedin") or row.get("LinkedIn") or None
        twitter   = row.get("twitter") or row.get("Twitter") or None
        telegram  = row.get("telegram") or row.get("Telegram") or None
        bio       = row.get("bio") or row.get("Bio") or None

        score, label, reason = score_participant(name, company, job_title, bio, None)
        p = Participant(
            event_id=event_id, name=name.strip(), company=company, job_title=job_title,
            email=email, linkedin_url=linkedin, twitter_handle=twitter,
            telegram_handle=telegram, bio=bio,
            score=score, score_label=label, score_reason=reason,
        )
        db.add(p)
        added += 1

    event.participant_count = db.query(Participant).filter(Participant.event_id == event_id).count()
    db.commit()
    return {"imported": added}


@app.patch("/api/participants/{participant_id}")
def update_participant(participant_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    p = db.query(Participant).filter(Participant.id == participant_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    if "notes" in payload:
        p.notes = payload["notes"]
    if "is_favorite" in payload:
        p.is_favorite = bool(payload["is_favorite"])
    db.commit()
    return _participant_dict(p)


@app.get("/api/favorites")
def get_favorites(
    workspace_id: Optional[int] = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    events = db.query(Event)
    if workspace_id:
        events = events.filter(Event.workspace_id == workspace_id)
    events = events.all()
    event_ids = [e.id for e in events]
    event_name_map = {e.id: e.name for e in events}
    if not event_ids:
        return []
    participants = (
        db.query(Participant)
        .filter(Participant.event_id.in_(event_ids), Participant.is_favorite == True)
        .order_by(Participant.score.desc())
        .all()
    )
    result = []
    for p in participants:
        d = _participant_dict(p)
        d["event_name"] = event_name_map.get(p.event_id, "")
        result.append(d)
    return result


@app.get("/api/participants/{participant_id}")
def get_participant(participant_id: int, db: Session = Depends(get_db)):
    p = db.query(Participant).filter(Participant.id == participant_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return _participant_dict(p)


@app.post("/api/participants/{participant_id}/enrich")
async def enrich_one(
    participant_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    p = db.query(Participant).filter(Participant.id == participant_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    if p.enriching:
        return {"status": "already_running"}
    p.enriching = True
    db.commit()
    background_tasks.add_task(_do_enrich, participant_id)
    return {"status": "started"}


@app.post("/api/events/{event_id}/enrich-all")
async def enrich_all(
    event_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    participants = (
        db.query(Participant)
        .filter(Participant.event_id == event_id, Participant.enriched == False)
        .order_by(Participant.score.desc())
        .all()
    )
    ids = [p.id for p in participants]
    for p in participants:
        p.enriching = True
    db.commit()
    background_tasks.add_task(_do_enrich_batch, ids)
    return {"status": "started", "count": len(ids)}


# ── Background tasks ──────────────────────────────────────────────────────────

async def _do_enrich(participant_id: int):
    from database import SessionLocal
    db = SessionLocal()
    try:
        p = db.query(Participant).filter(Participant.id == participant_id).first()
        if not p:
            return
        updates = await enrich_participant(p.name, p.company, p.job_title, p.linkedin_url)
        for k, v in updates.items():
            if v and not getattr(p, k):
                setattr(p, k, v)
        score, label, reason = score_participant(
            p.name, p.company, p.job_title, p.bio, p.company_description
        )
        p.score = score; p.score_label = label; p.score_reason = reason
        p.enriched = True; p.enriching = False
        db.commit()
    except Exception:
        p = db.query(Participant).filter(Participant.id == participant_id).first()
        if p:
            p.enriching = False
            db.commit()
    finally:
        db.close()


async def _do_enrich_batch(ids: list[int]):
    for pid in ids:
        await _do_enrich(pid)
        await asyncio.sleep(2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "workspace_id": e.workspace_id,
        "luma_id": e.luma_id,
        "name": e.name,
        "url": e.url,
        "date": e.date,
        "location": e.location,
        "participant_count": e.participant_count,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _participant_dict(p: Participant) -> dict:
    return {
        "id": p.id,
        "event_id": p.event_id,
        "name": p.name,
        "email": p.email,
        "company": p.company,
        "job_title": p.job_title,
        "linkedin_url": p.linkedin_url,
        "twitter_handle": p.twitter_handle,
        "telegram_handle": p.telegram_handle,
        "instagram_handle": p.instagram_handle,
        "tiktok_handle": p.tiktok_handle,
        "youtube_handle": p.youtube_handle,
        "website": p.website,
        "bio": p.bio,
        "company_description": p.company_description,
        "score": p.score,
        "score_label": p.score_label,
        "score_reason": p.score_reason,
        "enriched": p.enriched,
        "enriching": p.enriching,
        "avatar_url": p.avatar_url,
        "location": p.location,
        "notes": p.notes,
        "is_favorite": bool(p.is_favorite),
    }
