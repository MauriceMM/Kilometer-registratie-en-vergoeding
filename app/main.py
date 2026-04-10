"""
Kilometervergoeding App — FastAPI hoofdmodule.
Beveiligde web-app voor ritregistratie + SAP SuccessFactors export.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    create_access_token,
    hash_password,
    require_login,
    verify_password,
)
from app.database import create_tables, get_db
from app.models import Settings, Trip, TripStatus, TripType
from app.routers import export, ford, trips

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ALLOWED_HOST = os.getenv("ALLOWED_HOST", "kmv.melotto.nl")
DEFAULT_APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")


def _safe_login(request: Request) -> Optional[str]:
    """Login dependency die None teruggeeft in plaats van 401 te gooien (voor HTML pagina's)."""
    from jose import jwt, JWTError
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        from app.auth import SECRET_KEY, ALGORITHM
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

MAANDEN_NL = [
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december"
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialiseer database bij startup."""
    create_tables()
    _seed_default_password()
    logger.info("KMV app gestart")
    yield
    logger.info("KMV app gestopt")


def _seed_default_password():
    """Stel standaard app-wachtwoord in als er nog geen is."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        row = db.query(Settings).filter(Settings.key == "app_password_hash").first()
        if not row:
            db.add(Settings(key="app_password_hash", value=hash_password(DEFAULT_APP_PASSWORD)))
            db.commit()
            logger.warning(
                "Standaard app-wachtwoord ingesteld ('%s'). Verander dit via /instellingen!",
                DEFAULT_APP_PASSWORD,
            )
    finally:
        db.close()


app = FastAPI(
    title="Kilometervergoeding",
    description="Ritregistratie + SAP SuccessFactors export voor bruto leasevergoeding",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])  # Nginx regelt TLS

# Templates & static files
BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
_static_dir = os.path.join(BASE_DIR, "..", "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Routers
app.include_router(trips.router)
app.include_router(export.router)
app.include_router(ford.router)


# ──────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_pagina(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "fout": None})


@app.post("/login")
async def login(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.query(Settings).filter(Settings.key == "app_password_hash").first()
    if not row or not verify_password(password, row.value):
        return templates.TemplateResponse(
            "login.html", {"request": request, "fout": "Ongeldig wachtwoord"}, status_code=401
        )
    token = create_access_token({"sub": "admin"})
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        COOKIE_NAME, token,
        httponly=True, secure=True, samesite="lax",
        max_age=int(timedelta(hours=12).total_seconds()),
    )
    return resp


@app.post("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ──────────────────────────────────────────────
# Hoofd pagina's (HTML)
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(_safe_login),
):
    if not user:
        return RedirectResponse(url="/login")

    # Actieve rit
    actieve_rit = db.query(Trip).filter(Trip.status == TripStatus.ACTIEF).first()

    # Huidige maand statistieken
    nu = datetime.now(timezone.utc)
    begin_maand = datetime(nu.year, nu.month, 1)
    deze_maand_ritten = (
        db.query(Trip)
        .filter(
            Trip.datum >= begin_maand,
            Trip.type == TripType.ZAKELIJK,
            Trip.status == TripStatus.AFGESLOTEN,
        )
        .all()
    )
    km_deze_maand = sum(r.afstand_km or 0 for r in deze_maand_ritten)
    vergoeding_deze_maand = sum(r.vergoeding_eur or 0 for r in deze_maand_ritten)

    # Recente ritten (laatste 10)
    recente_ritten = (
        db.query(Trip)
        .order_by(Trip.datum.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse("index.html", {
        "request": request,
        "actieve_rit": actieve_rit,
        "km_deze_maand": round(km_deze_maand, 1),
        "vergoeding_deze_maand": round(vergoeding_deze_maand, 2),
        "aantal_ritten_maand": len(deze_maand_ritten),
        "recente_ritten": recente_ritten,
        "huidige_maand": MAANDEN_NL[nu.month].capitalize(),
        "huidig_jaar": nu.year,
        "huidig_maand_nr": nu.month,
    })


@app.get("/overzicht", response_class=HTMLResponse)
async def overzicht(
    request: Request,
    jaar: Optional[int] = None,
    maand: Optional[int] = None,
    db: Session = Depends(get_db),
    user: str = Depends(_safe_login),
):
    if not user:
        return RedirectResponse(url="/login")

    nu = datetime.now(timezone.utc)
    jaar = jaar or nu.year
    maand = maand or nu.month

    # Bouw maandoverzicht
    begin = datetime(jaar, maand, 1)
    eind = datetime(jaar, maand + 1, 1) if maand < 12 else datetime(jaar + 1, 1, 1)

    ritten = (
        db.query(Trip)
        .filter(Trip.datum >= begin, Trip.datum < eind)
        .order_by(Trip.datum.asc())
        .all()
    )

    zakelijke = [r for r in ritten if r.type == TripType.ZAKELIJK and r.status == TripStatus.AFGESLOTEN]
    totaal_km = sum(r.afstand_km or 0 for r in zakelijke)
    totaal_vergoeding = sum(r.vergoeding_eur or 0 for r in zakelijke)

    # Navigatie maanden
    vorige_maand = (maand - 1) if maand > 1 else 12
    vorig_jaar = jaar if maand > 1 else jaar - 1
    volgende_maand = (maand + 1) if maand < 12 else 1
    volgend_jaar = jaar if maand < 12 else jaar + 1

    return templates.TemplateResponse("overzicht.html", {
        "request": request,
        "ritten": ritten,
        "zakelijke_ritten": zakelijke,
        "jaar": jaar,
        "maand": maand,
        "maand_naam": MAANDEN_NL[maand].capitalize(),
        "totaal_km": round(totaal_km, 1),
        "totaal_vergoeding": round(totaal_vergoeding, 2),
        "vorige_maand": vorige_maand,
        "vorig_jaar": vorig_jaar,
        "volgende_maand": volgende_maand,
        "volgend_jaar": volgend_jaar,
    })


@app.get("/instellingen", response_class=HTMLResponse)
async def instellingen_pagina(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(_safe_login),
):
    if not user:
        return RedirectResponse(url="/login")

    instellingen = {
        row.key: row.value
        for row in db.query(Settings).all()
        if row.key not in ("app_password_hash", "ford_password_encrypted")
    }
    return templates.TemplateResponse("instellingen.html", {
        "request": request,
        "instellingen": instellingen,
        "opgeslagen": request.query_params.get("opgeslagen") == "1",
    })


@app.post("/instellingen")
async def sla_instellingen_op(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(_safe_login),
    ford_username: str = Form(""),
    ford_password: str = Form(""),
    ford_vin: str = Form(""),
    tarief_per_km: str = Form("0.23"),
    werknemer_naam: str = Form(""),
    werknemer_nummer: str = Form(""),
    app_password: str = Form(""),
):
    if not user:
        return RedirectResponse(url="/login")

    def sla_op(key: str, value: str):
        if not value.strip():
            return
        row = db.query(Settings).filter(Settings.key == key).first()
        if row:
            row.value = value.strip()
        else:
            db.add(Settings(key=key, value=value.strip()))

    sla_op("ford_username", ford_username)
    if ford_password.strip():
        sla_op("ford_password_encrypted", ford_password)  # TODO: versleutelen
    sla_op("ford_vin", ford_vin)
    sla_op("tarief_per_km", tarief_per_km)
    sla_op("werknemer_naam", werknemer_naam)
    sla_op("werknemer_nummer", werknemer_nummer)
    if app_password.strip():
        row = db.query(Settings).filter(Settings.key == "app_password_hash").first()
        if row:
            row.value = hash_password(app_password)
        else:
            db.add(Settings(key="app_password_hash", value=hash_password(app_password)))

    db.commit()
    return RedirectResponse(url="/instellingen?opgeslagen=1", status_code=302)


# Health check (voor Docker/load balancer)
@app.get("/health")
async def health():
    return {"status": "ok"}
