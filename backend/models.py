from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    luma_id = Column(String, unique=True, nullable=True)
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
    created_at = Column(DateTime, default=datetime.utcnow)
