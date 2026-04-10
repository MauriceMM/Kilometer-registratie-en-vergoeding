# Deployment handleiding — kmv.melotto.nl

## Vereisten op je VPS
- Ubuntu 22.04 / Debian 12
- Docker + Docker Compose (v2)
- Poort 80 en 443 open in firewall
- DNS: `kmv.melotto.nl` → IP-adres van je server

---

## Stap 1 — Code op de server zetten

```bash
# Kopieer de map naar de server (of clone via git)
scp -r kmv-app/ gebruiker@jouw-server:/opt/kmv-app/

# Of via git (maak eerst een repo):
# git clone https://github.com/jij/kmv-app /opt/kmv-app
```

---

## Stap 2 — .env aanmaken

```bash
cd /opt/kmv-app
cp .env.example .env
nano .env
```

Vul in:
```
APP_PASSWORD=kies-een-sterk-wachtwoord
SECRET_KEY=$(openssl rand -hex 32)
```

---

## Stap 3 — Let's Encrypt certificaat aanvragen

```bash
cd /opt/kmv-app

# Stap 3a: Start nginx tijdelijk met alleen HTTP (voor ACME challenge)
# Commenteer de HTTPS-server blok tijdelijk uit in nginx/conf.d/kmv.conf
# (of gebruik de tijdelijke config hieronder)

docker compose up -d nginx

# Stap 3b: Vraag certificaat aan
docker compose run --rm certbot certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email jouw-email@example.com \
  --agree-tos \
  --no-eff-email \
  -d kmv.melotto.nl

# Stap 3c: Herstel nginx config (HTTPS weer aanzetten)
# Zorg dat nginx/conf.d/kmv.conf de HTTPS server blok heeft
docker compose restart nginx
```

---

## Stap 4 — App starten

```bash
cd /opt/kmv-app
docker compose up -d --build
```

Controleer of alles draait:
```bash
docker compose ps
docker compose logs app
```

De app is nu bereikbaar op: **https://kmv.melotto.nl**

---

## Stap 5 — Eerste configuratie in de app

1. Ga naar **https://kmv.melotto.nl**
2. Log in met het wachtwoord uit `.env` (APP_PASSWORD)
3. Ga naar **Instellingen** en vul in:
   - FordPass gebruikersnaam + wachtwoord
   - VIN van je auto (staat op kentekenbewijs, veld E)
   - Jouw naam en personeelsnummer
4. Klik **Test Ford API verbinding** — als dit werkt, staat alles goed

---

## Stap 6 — Dagelijks gebruik

### Rit starten
1. Open **https://kmv.melotto.nl**
2. Klik **Rit registreren**
3. Kies **Zakelijk** of **Privé**
4. Klik **🚗 Ford** om km-stand automatisch op te halen (of voer handmatig in)
5. Klik **Start rit**

### Rit stoppen
- Banner bovenaan: klik **⏹ Rit stoppen**
- Haal de eindstand op via Ford of voer in
- Rit wordt afgesloten + vergoeding berekend

### Handmatig rit invoeren
- **Rit registreren → Handmatig**
- Voer begin- én eindstand in

---

## Maandelijkse declaratie (SAP SuccessFactors)

1. Ga naar **Overzicht** → kies de juiste maand
2. Klik **⬇ Download Excel** voor het declaratie-overzicht
3. Open SAP SuccessFactors:
   - **View my profile → Employment Information → Commuter Traffic**
   - Klik het potlood naast **Home/Office Kilometer Info**
4. Voer per dag in de Excel-lijst de km in (kies "Office")
5. Deadline: **laatste dag van de maand**

---

## Updates

```bash
cd /opt/kmv-app
git pull  # als je git gebruikt
docker compose up -d --build
```

## Backup database

```bash
docker cp kmv-app:/app/data/kmv.db ./backup_kmv_$(date +%Y%m%d).db
```

## Logs bekijken

```bash
docker compose logs -f app      # App logs
docker compose logs -f nginx    # Nginx logs
```

## Certificaat handmatig verlengen

```bash
docker compose run --rm certbot certbot renew
docker compose restart nginx
```

Certificaten worden automatisch elke 12 uur gecontroleerd en verlengd.
