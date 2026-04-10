"""Pydantic schemas voor request/response validatie."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models import TripStatus, TripType


class TripCreate(BaseModel):
    type: TripType
    start_locatie: Optional[str] = None
    omschrijving: Optional[str] = None
    project_code: Optional[str] = None
    klant: Optional[str] = None
    tarief_per_km: float = 0.23


class TripUpdate(BaseModel):
    eind_locatie: Optional[str] = None
    eind_km: Optional[float] = None
    omschrijving: Optional[str] = None
    project_code: Optional[str] = None
    klant: Optional[str] = None


class TripManualCreate(BaseModel):
    """Voor handmatig invoeren van een complete rit."""
    type: TripType
    datum: Optional[datetime] = None
    start_km: float
    eind_km: float
    start_locatie: Optional[str] = None
    eind_locatie: Optional[str] = None
    omschrijving: Optional[str] = None
    project_code: Optional[str] = None
    klant: Optional[str] = None
    tarief_per_km: float = 0.23


class TripResponse(BaseModel):
    id: int
    datum: Optional[datetime]
    type: TripType
    status: TripStatus
    start_km: Optional[float]
    eind_km: Optional[float]
    start_locatie: Optional[str]
    eind_locatie: Optional[str]
    start_tijd: Optional[datetime]
    eind_tijd: Optional[datetime]
    afstand_km: Optional[float]
    omschrijving: Optional[str]
    project_code: Optional[str]
    klant: Optional[str]
    tarief_per_km: float
    vergoeding_eur: Optional[float]

    model_config = {"from_attributes": True}


class MonthSummary(BaseModel):
    jaar: int
    maand: int
    maand_naam: str
    totaal_zakelijk_km: float
    totaal_vergoeding_eur: float
    aantal_ritten: int


class LoginRequest(BaseModel):
    password: str


class SettingsUpdate(BaseModel):
    ford_username: Optional[str] = None
    ford_password: Optional[str] = None
    ford_vin: Optional[str] = None
    tarief_per_km: Optional[float] = None
    werknemer_naam: Optional[str] = None
    werknemer_nummer: Optional[str] = None
    app_password: Optional[str] = None
