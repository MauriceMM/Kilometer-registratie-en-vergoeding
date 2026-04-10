"""API routes voor ritbeheer."""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.models import Trip, TripStatus, TripType
from app.schemas import TripCreate, TripManualCreate, TripResponse, TripUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trips", tags=["trips"])


def _finish_trip(trip: Trip, eind_km: float, eind_locatie: Optional[str] = None) -> Trip:
    """Sluit een rit af en bereken vergoeding."""
    trip.eind_km = eind_km
    trip.eind_locatie = eind_locatie
    trip.eind_tijd = datetime.now(timezone.utc)
    trip.status = TripStatus.AFGESLOTEN
    trip.bereken_vergoeding()
    return trip


@router.get("", response_model=List[TripResponse])
def lijst_ritten(
    jaar: Optional[int] = Query(None),
    maand: Optional[int] = Query(None),
    type: Optional[TripType] = Query(None),
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Haal lijst van ritten op, optioneel gefilterd op maand/jaar/type."""
    query = db.query(Trip).order_by(Trip.datum.desc())
    if jaar:
        query = query.filter(Trip.datum.between(
            datetime(jaar, maand or 1, 1),
            datetime(jaar, maand or 12, 31, 23, 59, 59),
        ))
    if type:
        query = query.filter(Trip.type == type)
    return query.all()


@router.post("", response_model=TripResponse, status_code=201)
def maak_rit(
    data: TripCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Start een nieuwe rit (km-stand wordt later ingevuld via Ford API of handmatig)."""
    trip = Trip(
        type=data.type,
        start_locatie=data.start_locatie,
        start_tijd=datetime.now(timezone.utc),
        omschrijving=data.omschrijving,
        project_code=data.project_code,
        klant=data.klant,
        tarief_per_km=data.tarief_per_km,
        status=TripStatus.ACTIEF,
        datum=datetime.now(timezone.utc),
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.post("/handmatig", response_model=TripResponse, status_code=201)
def maak_handmatige_rit(
    data: TripManualCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Voer een complete rit handmatig in (start én eind km-stand direct)."""
    datum = data.datum or datetime.now(timezone.utc)
    trip = Trip(
        type=data.type,
        datum=datum,
        start_km=data.start_km,
        eind_km=data.eind_km,
        start_locatie=data.start_locatie,
        eind_locatie=data.eind_locatie,
        start_tijd=datum,
        eind_tijd=datum,
        omschrijving=data.omschrijving,
        project_code=data.project_code,
        klant=data.klant,
        tarief_per_km=data.tarief_per_km,
        status=TripStatus.AFGESLOTEN,
    )
    trip.bereken_vergoeding()
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.get("/actief", response_model=Optional[TripResponse])
def actieve_rit(
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Geeft de actieve (nog lopende) rit terug, of null als er geen is."""
    trip = db.query(Trip).filter(Trip.status == TripStatus.ACTIEF).first()
    return trip


@router.get("/{trip_id}", response_model=TripResponse)
def haal_rit_op(
    trip_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Rit niet gevonden")
    return trip


@router.patch("/{trip_id}/start-km", response_model=TripResponse)
def stel_start_km_in(
    trip_id: int,
    km: float,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Stel de beginkilometerstand in op een actieve rit."""
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Rit niet gevonden")
    trip.start_km = km
    db.commit()
    db.refresh(trip)
    return trip


@router.patch("/{trip_id}/stop", response_model=TripResponse)
def stop_rit(
    trip_id: int,
    eind_km: float,
    eind_locatie: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Sluit een actieve rit af met de eindkilometerstand."""
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Rit niet gevonden")
    if trip.status != TripStatus.ACTIEF:
        raise HTTPException(status_code=400, detail="Rit is al afgesloten")
    _finish_trip(trip, eind_km, eind_locatie)
    db.commit()
    db.refresh(trip)
    return trip


@router.put("/{trip_id}", response_model=TripResponse)
def update_rit(
    trip_id: int,
    data: TripUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Pas omschrijving, locaties of km-standen aan."""
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Rit niet gevonden")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(trip, field, value)
    if data.eind_km is not None and trip.start_km is not None:
        trip.bereken_vergoeding()
    db.commit()
    db.refresh(trip)
    return trip


@router.delete("/{trip_id}", status_code=204)
def verwijder_rit(
    trip_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Rit niet gevonden")
    db.delete(trip)
    db.commit()
