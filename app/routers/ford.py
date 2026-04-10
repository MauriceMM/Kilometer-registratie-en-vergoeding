"""Ford API routes: ophalen km-stand via FordPass."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_login
from app.database import get_db
from app.fordpass import FordPassClient, FordPassError
from app.models import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ford", tags=["ford"])

# Singleton Ford client (geïnitialiseerd bij eerste aanroep)
_ford_client: Optional[FordPassClient] = None


def _haal_instelling(db: Session, key: str) -> Optional[str]:
    row = db.query(Settings).filter(Settings.key == key).first()
    return row.value if row else None


async def _get_client(db: Session) -> FordPassClient:
    """Geef een geauthenticeerde FordPass client terug."""
    global _ford_client
    username = _haal_instelling(db, "ford_username")
    password = _haal_instelling(db, "ford_password_encrypted")  # plaintext opgeslagen, of encrypteer later
    vin = _haal_instelling(db, "ford_vin")

    if not all([username, password, vin]):
        raise HTTPException(
            status_code=400,
            detail="Ford credentials niet ingesteld. Ga naar Instellingen om username, wachtwoord en VIN in te vullen.",
        )

    # Maak een nieuwe client als credentials zijn gewijzigd
    if (
        _ford_client is None
        or _ford_client.username != username
        or _ford_client.vin != vin
    ):
        _ford_client = FordPassClient(username, password, vin)

    return _ford_client


@router.get("/odometer")
async def haal_odometer_op(
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """
    Haalt de actuele kilometerstand op via de FordPass API.
    Retourneert de km-stand als float.
    """
    client = await _get_client(db)
    try:
        km = await client.get_odometer()
        if km is None:
            raise HTTPException(status_code=502, detail="Odometer niet beschikbaar in Ford API respons")
        return {"km_stand": km, "bron": "ford_api"}
    except FordPassError as e:
        raise HTTPException(status_code=502, detail=f"FordPass fout: {e}")
    except Exception as e:
        logger.exception("Fout bij ophalen odometer")
        # Verwijder client zodat authenticatie opnieuw geprobeerd wordt
        _ford_client = None
        raise HTTPException(status_code=502, detail=f"Ford API fout: {str(e)[:200]}")


@router.post("/auth/reset")
async def reset_ford_auth(
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Forceer een nieuwe authenticatie bij Ford (handig als token verlopen is)."""
    global _ford_client
    _ford_client = None
    return {"status": "ok", "bericht": "Ford auth gereset, volgende aanroep authenticeert opnieuw"}


@router.get("/vehicle")
async def haal_voertuig_op(
    db: Session = Depends(get_db),
    user: str = Depends(require_login),
):
    """Basisinformatie over het gekoppelde voertuig."""
    client = await _get_client(db)
    try:
        info = await client.get_vehicle_info()
        return info
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
