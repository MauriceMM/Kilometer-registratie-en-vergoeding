"""Database modellen voor de kilometervergoeding app."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class TripType(str, PyEnum):
    ZAKELIJK = "zakelijk"
    PRIVE = "prive"


class TripStatus(str, PyEnum):
    ACTIEF = "actief"       # rit is gestart, nog niet afgesloten
    AFGESLOTEN = "afgesloten"  # rit klaar


class Trip(Base):
    """Een enkele rit (zakelijk of privé)."""
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    datum = Column(DateTime, default=datetime.utcnow, nullable=False)
    type = Column(Enum(TripType), nullable=False)
    status = Column(Enum(TripStatus), default=TripStatus.ACTIEF, nullable=False)

    # Vertrekpunt
    start_km = Column(Float, nullable=True)
    start_locatie = Column(String(200), nullable=True)
    start_tijd = Column(DateTime, nullable=True)

    # Bestemming
    eind_km = Column(Float, nullable=True)
    eind_locatie = Column(String(200), nullable=True)
    eind_tijd = Column(DateTime, nullable=True)

    # Berekend
    afstand_km = Column(Float, nullable=True)  # eind_km - start_km

    # Extra info
    omschrijving = Column(Text, nullable=True)
    project_code = Column(String(50), nullable=True)  # optioneel, voor CTAC declaratie
    klant = Column(String(200), nullable=True)

    # Vergoeding (standaard €0.23/km zakelijk, conform Belastingdienst 2024/2025)
    tarief_per_km = Column(Float, default=0.23, nullable=False)
    vergoeding_eur = Column(Float, nullable=True)  # afstand_km * tarief_per_km

    # Ford API metadata
    ford_odometer_start = Column(Float, nullable=True)  # ruwe Ford API waarde
    ford_odometer_eind = Column(Float, nullable=True)

    def bereken_vergoeding(self) -> None:
        """Herbereken afstand en vergoeding na invullen km-standen."""
        if self.start_km is not None and self.eind_km is not None:
            self.afstand_km = round(self.eind_km - self.start_km, 1)
            if self.type == TripType.ZAKELIJK:
                self.vergoeding_eur = round(self.afstand_km * self.tarief_per_km, 2)
            else:
                self.vergoeding_eur = 0.0

    def __repr__(self) -> str:
        return (
            f"<Trip id={self.id} {self.type} {self.datum.date() if self.datum else '?'} "
            f"{self.afstand_km or 0:.0f} km>"
        )


class Settings(Base):
    """App-instellingen (Ford credentials, tarief, etc.)."""
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)

    @classmethod
    def get_all_keys(cls):
        return [
            "ford_username",
            "ford_password_encrypted",
            "ford_vin",
            "tarief_per_km",
            "werknemer_naam",
            "werknemer_nummer",
            "app_password_hash",
        ]
