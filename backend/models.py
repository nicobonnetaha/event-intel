from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)   # prénom / slug, e.g. "Nicolas", "Enzo"
    pin = Column(String, nullable=True)  # PIN optionnel (plaintext – outil interne)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)  # prefixed: "ws_{id}:{key}"
    value = Column(Text, nullable=True)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    luma_id = Column(String, nullable=True)   # unique per workspace, checked in code
    name = Column(String)
    url = Column(String)
    date = Column(String, nullable=True)
    location = Column(String, nullable=True)
    participant_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Participant(Base):
    __tablename__ = "participants"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"))
    luma_user_id = Column(String, nullable=True)
    name = Column(String)
    email = Column(String, nullable=True)
    company = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    twitter_handle = Column(String, nullable=True)
    telegram_handle = Column(String, nullable=True)
    instagram_handle = Column(String, nullable=True)
    tiktok_handle = Column(String, nullable=True)
    youtube_handle = Column(String, nullable=True)
    website = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    company_description = Column(Text, nullable=True)
    score = Column(Float, default=0)
    score_label = Column(String, nullable=True)
    score_reason = Column(Text, nullable=True)
    enriched = Column(Boolean, default=False)
    enriching = Column(Boolean, default=False)
    avatar_url = Column(String, nullable=True)
    location = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_favorite = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
