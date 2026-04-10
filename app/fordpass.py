"""
FordPass API client - haalt km-stand (odometer) op via de onofficiële FordPass/Autonomic API.
Gebaseerd op de open-source Home Assistant integratie (github.com/itchannel/fordpass-ha).
"""

import hashlib
import logging
import os
import re
import time
from base64 import urlsafe_b64encode
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

# Ford API basis-URLs
FORD_LOGIN_URL = "https://sso.ci.ford.com"
FORD_MPS_URL = "https://api.mps.ford.com/api"
FORD_AUTONOMIC_URL = "https://api.autonomic.ai"
FORD_USAPI_URL = "https://usapi.cv.ford.com/api"

COUNTRY_CODE = "NLD"  # Nederland
CLIENT_ID = "9fb503e0-715b-47e8-adfd-ad4b7770f73b"  # FordPass client ID (publiek)

HEADERS_DEFAULT = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "fordpass-nl/1.0",
    "Content-Type": "application/json",
}


class FordPassError(Exception):
    pass


class FordPassClient:
    """
    Asynchrone client voor de FordPass API.
    Authenticeer met je FordPass gebruikersnaam en wachtwoord.
    """

    def __init__(self, username: str, password: str, vin: str):
        self.username = username
        self.password = password
        self.vin = vin
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._autonomic_token: Optional[str] = None
        self._token_expiry: float = 0

    def _generate_code_verifier(self) -> tuple[str, str]:
        """Genereer PKCE code verifier + challenge."""
        code_verifier = urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("utf-8")
        code_challenge = urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode("utf-8")
        return code_verifier, code_challenge

    async def _auth_step1(self, client: httpx.AsyncClient) -> str:
        """Stap 1: Azure B2C login, geeft authorization code terug."""
        code_verifier, code_challenge = self._generate_code_verifier()
        self._code_verifier = code_verifier

        # Start de authorization flow
        auth_params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "scope": "openid profile",
            "redirect_uri": "fordapp://userauthorized",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        policy = f"B2C_1A_SignInSignUp_{COUNTRY_CODE}"
        base = f"{FORD_LOGIN_URL}/4566605f-43a7-400a-946e-89cc9fdb0bd7/{policy}"

        # Haal de login-pagina op om CSRF en transId te krijgen
        resp = await client.get(
            f"{base}/oauth2/v2.0/authorize",
            params=auth_params,
            follow_redirects=True,
        )
        resp.raise_for_status()

        # Extract csrf en transId
        csrf = re.search(r'"csrf":"([^"]+)"', resp.text)
        trans_id = re.search(r'"transId":"([^"]+)"', resp.text)
        if not csrf or not trans_id:
            raise FordPassError("Kon CSRF/transId niet vinden in login-pagina. Mogelijk Ford API-wijziging.")

        csrf_token = csrf.group(1)
        trans_id_val = trans_id.group(1)

        # Submit credentials
        cred_resp = await client.post(
            f"{base}/SelfAsserted",
            params={"tx": trans_id_val, "p": policy},
            data={
                "request_type": "RESPONSE",
                "signInName": self.username,
                "password": self.password,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRF-TOKEN": csrf_token,
            },
        )
        cred_resp.raise_for_status()

        # Haal redirect met authorization code op
        confirm_resp = await client.get(
            f"{base}/api/CombinedSigninAndSignup/confirmed",
            params={
                "rememberMe": "false",
                "csrf_token": csrf_token,
                "tx": trans_id_val,
                "p": policy,
            },
            follow_redirects=False,
        )

        # De redirect bevat de authorization code
        redirect_url = confirm_resp.headers.get("Location", "")
        parsed = urlparse(redirect_url)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            raise FordPassError(f"Authorization code niet gevonden in redirect: {redirect_url}")
        return code

    async def _auth_step2(self, client: httpx.AsyncClient, auth_code: str) -> dict:
        """Stap 2: Wissel authorization code in voor access + refresh tokens."""
        policy = f"B2C_1A_SignInSignUp_{COUNTRY_CODE}"
        token_url = (
            f"{FORD_LOGIN_URL}/4566605f-43a7-400a-946e-89cc9fdb0bd7"
            f"/{policy}/oauth2/v2.0/token"
        )
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": auth_code,
                "redirect_uri": "fordapp://userauthorized",
                "code_verifier": self._code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()

    async def _get_ford_token(self, client: httpx.AsyncClient, b2c_token: str) -> dict:
        """Wissel B2C token in voor Ford MPS API token."""
        resp = await client.post(
            f"{FORD_MPS_URL}/token/v2/cat-with-b2c-access-token",
            json={"idpToken": b2c_token},
            headers={**HEADERS_DEFAULT, "Application-Id": "71A3AD0A-CF46-4CCF-B473-FC7FE5BC4592"},
        )
        resp.raise_for_status()
        return resp.json()

    async def _get_autonomic_token(self, client: httpx.AsyncClient, ford_token: str) -> str:
        """Haal Autonomic API token op (voor telemetrie/odometer)."""
        resp = await client.post(
            f"{FORD_AUTONOMIC_URL}/v1/auth/oidc/token",
            data={
                "subject_token": ford_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "client_id": "fordpass-prod",
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "requested_token_type": "urn:ietf:params:oauth:token-type:jwt",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def authenticate(self) -> None:
        """Voer volledige authenticatie uit en sla tokens op."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            logger.info("FordPass authenticatie gestart voor %s", self.username)
            auth_code = await self._auth_step1(client)
            b2c_tokens = await self._auth_step2(client, auth_code)
            ford_tokens = await self._get_ford_token(client, b2c_tokens["access_token"])
            self._access_token = ford_tokens.get("access_token")
            self._refresh_token = ford_tokens.get("refresh_token")
            self._autonomic_token = await self._get_autonomic_token(client, self._access_token)
            self._token_expiry = time.time() + ford_tokens.get("expires_in", 3600) - 60
            logger.info("FordPass authenticatie geslaagd")

    async def refresh_tokens(self) -> None:
        """Vernieuw tokens via refresh token."""
        if not self._refresh_token:
            await self.authenticate()
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{FORD_MPS_URL}/token/v2/cat-with-refresh-token",
                json={"refresh_token": self._refresh_token},
                headers={**HEADERS_DEFAULT, "Application-Id": "71A3AD0A-CF46-4CCF-B473-FC7FE5BC4592"},
            )
            if resp.status_code != 200:
                logger.warning("Token refresh mislukt, opnieuw authenticeren...")
                await self.authenticate()
                return
            ford_tokens = resp.json()
            self._access_token = ford_tokens.get("access_token")
            self._refresh_token = ford_tokens.get("refresh_token", self._refresh_token)
            self._autonomic_token = await self._get_autonomic_token(client, self._access_token)
            self._token_expiry = time.time() + ford_tokens.get("expires_in", 3600) - 60

    async def _ensure_valid_token(self) -> None:
        """Controleer of token geldig is; refresh indien nodig."""
        if not self._access_token or time.time() >= self._token_expiry:
            await self.refresh_tokens()

    async def get_odometer(self) -> Optional[float]:
        """
        Geeft de huidige kilometerstand terug (in km).
        Ford API geeft doorgaans kilometers terug voor Europese voertuigen.
        """
        await self._ensure_valid_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{FORD_AUTONOMIC_URL}/v1beta/telemetry/sources/fordpass/vehicles/{self.vin}:query",
                json={},
                headers={
                    "Authorization": f"Bearer {self._autonomic_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Pad: metrics.odometer.value (soms genest onder 'states')
        metrics = data.get("metrics") or data.get("states", {})
        odometer = metrics.get("odometer", {})
        if isinstance(odometer, dict):
            value = odometer.get("value")
            if value is not None:
                return float(value)

        logger.warning("Odometer niet gevonden in respons: %s", list(metrics.keys()))
        return None

    async def get_vehicle_info(self) -> dict:
        """Haal basisinformatie over het voertuig op."""
        await self._ensure_valid_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{FORD_USAPI_URL}/users/vehicles",
                headers={
                    "Auth-Token": self._access_token,
                    "Application-Id": "71A3AD0A-CF46-4CCF-B473-FC7FE5BC4592",
                    **HEADERS_DEFAULT,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        vehicles = data.get("userVehicles", {}).get("vehicleDetails", [])
        for v in vehicles:
            if v.get("VIN", "").upper() == self.vin.upper():
                return v
        return {"VIN": self.vin, "vehicles_found": len(vehicles)}
