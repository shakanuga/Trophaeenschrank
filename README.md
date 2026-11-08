# Trophäenschrank

Selbst gehosteter Tracker für 100-%-Spiele und Platin-Trophäen – im Look der Steam-Bibliothek.

- **Steam**: liest die komplette Bibliothek samt Erfolgen aus. 100 % wird automatisch erkannt, das Abschlussdatum ist der Zeitpunkt des letzten Erfolgs.
- **PlayStation**: Trophäenlisten über das NPSSO-Token (dieselbe Schnittstelle wie die PlayStation-App). Platin wird erkannt, Datum = Platin-Trophäe.
- **Xbox**: über [OpenXBL](https://xbl.io) (kostenloser Key).
- **Nintendo / Sonstige**: von Hand über ＋ (Nintendo hat keine Erfolge-Schnittstelle).
- Status-Bänder wie in Steam: **Spielt · Durchgespielt · 100 % · Platin · Backlog · Pausiert**, dazu eigene Tags, Notizen, Filter nach Plattform/Status/Jahr/Tag, Gruppierung nach Jahr, Jahresstatistik.
- **Cover-Stile umschaltbar** (Auswahl oben rechts): offizielle Steam-Cover, SteamGridDB-Stile (Alternate, Material, White Logo, Ohne Logo, Blurred) und beliebig viele **eigene Quellen per URL-Vorlage**, z. B. ein GitHub-Repo. Pro Spiel kann man zusätzlich ein Cover aus allen Vorschlägen auswählen oder eine eigene URL einfügen. Cover werden lokal gecacht.
- Automatischer Abgleich im Hintergrund (Standard: alle 6 Stunden), Backup als JSON exportieren/importieren.

## Installation (Unraid / Docker)

Das fertige Image wird bei jedem Push automatisch gebaut: `ghcr.io/shakanuga/trophaeenschrank:latest` (amd64 und arm64).

**Unraid:** Docker → „Add Container“ und das Template aus `unraid/trophaeenschrank.xml` nutzen – oder von Hand: Repository `ghcr.io/shakanuga/trophaeenschrank:latest`, Port `8766`, Pfad `/data` → `/mnt/user/appdata/trophaeenschrank`.

**Docker Compose:**

```bash
docker compose up -d
```

Danach `http://<server>:8766` öffnen. Daten liegen in `/mnt/user/appdata/trophaeenschrank` (SQLite + Cover-Cache). Der Container läuft als `99:100` (nobody:users).

Hinter einem Reverse-Proxy (z.B. Nginx Proxy Manager) einfach einen Proxy-Host auf `<server-ip>:8766` anlegen. Die App hat **keine eigene Anmeldung** – also nur im LAN/VPN erreichbar machen oder im Proxy eine Zugriffsbeschränkung davorsetzen.

## Zugangsdaten (⚙ Einstellungen)

| Plattform | Was | Wo |
|---|---|---|
| Steam | Web-API-Key + Steam-ID/Profil-URL | https://steamcommunity.com/dev/apikey – Profil → Privatsphäre → „Spieldetails“ auf **öffentlich** |
| PlayStation | NPSSO-Token | bei playstation.com anmelden, dann https://ca.account.sony.com/api/v1/ssocookie öffnen und den `npsso`-Wert kopieren (läuft nach ~2 Monaten ab) |
| Xbox | OpenXBL-Key | https://xbl.io → mit Xbox-Konto anmelden → API-Key |
| Cover | SteamGridDB-Key (optional) | https://www.steamgriddb.com/profile/preferences/api |

## Spielhülle

Cover-Stil „Spielhülle“ setzt jedes Cover in eine Spielhülle – Steam-Spiele in die Steam-Hülle (Farbe wählbar), PlayStation-, Xbox- und Nintendo-Spiele in die passende Konsolen-Hülle (PS3/PS4/PS5, Xbox 360/One/Series, Switch/Switch 2). 100-%-Spiele bekommen Rosette und „100% Complete“-Band, wahlweise nur die Rosette oder einen Goldrahmen.

PlayStation-Spiele mit Platin bekommen stattdessen eine Platin-Trophäe und ein „PLATIN“-Band (eigene Zeichnung, abschaltbar). Xbox und Nintendo haben kein Gegenstück zur Platin-Trophäe und behalten die Rosette.

Die Hüllen-Grafiken stammen aus [diegobergonsi/steam-case-covers](https://github.com/diegobergonsi/steam-case-covers) (GPL-3.0). Sie sind **nicht** in diesem Projekt enthalten, sondern werden beim ersten Gebrauch von GitHub nach `/data/case-assets` geladen („Hüllen neu von GitHub laden“ in den Einstellungen holt Updates). Die erzeugten Cover enthalten Artwork der Spiele-Publisher – nur für den privaten Gebrauch.

## Eigene Cover-Quellen

In den Einstellungen unter „Eigene Cover-Quellen“, eine Zeile pro Quelle:

```
Mein Repo | https://raw.githubusercontent.com/NUTZER/REPO/main/covers/{appid}.jpg
```

Platzhalter: `{appid}` (Steam-AppID bzw. Plattform-ID), `{title}` (URL-kodiert), `{title_raw}`, `{slug}` (`watch-dogs`), `{title_underscore}`, `{platform}`.
Gibt es für ein Spiel kein Bild, fällt die App automatisch auf das offizielle Cover zurück.

## Status-Logik

- Alle Erfolge / Platin → **100 %** (überschreibt immer, auch manuell gesetzte Status).
- In den letzten zwei Wochen gespielt → **Spielt** (solange der Status automatisch ist).
- „Durchgespielt“, „Backlog“, „Pausiert“ setzt du selbst – die bleiben beim Abgleich erhalten.
- Kommen per DLC neue Erfolge dazu, fällt ein 100-%-Spiel auf „Durchgespielt“ zurück.

## Anmeldung mit Pocket ID

Ohne Einstellungen ist der Trophäenschrank offen für alle, die die Adresse erreichen. Mit Pocket ID fragt er vor jedem Zugriff nach einer Anmeldung.

1. In Pocket ID einen OIDC-Client `Trophäenschrank` anlegen, Callback-URL `https://trophaeen.example.de/auth/pocketid/zurueck`. Unter „Allowed User Groups“ festlegen, wer rein darf.
2. Am Container `OIDC_ISSUER` (z. B. `https://id.example.de`), `OIDC_CLIENT_ID` und `OIDC_CLIENT_SECRET` setzen.
3. Optional: `OIDC_ALLOWED_GROUPS`, `OIDC_LABEL`, `OIDC_REDIRECT_URI`.

Die Anmeldung gilt 180 Tage, abmelden über `/auth/abmelden`. `/healthz` und das Manifest bleiben offen.

## Entwicklung

```bash
pip install -r requirements.txt
DATA_DIR=./data flask --app app.main run --port 8766
python -m tests.test_app   # Tests mit nachgebauten API-Antworten
```

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE).

Die Spielhüllen-Funktion (`app/casecover.py`) ist an [steam-case-covers](https://github.com/diegobergonsi/steam-case-covers) von Diego Bergonsi angelehnt (ebenfalls GPL-3.0). Dessen Grafiken und die Schrift Nunito Sans (SIL OFL 1.1) sind nicht in diesem Repo enthalten, sondern werden zur Laufzeit von GitHub geladen. Marken wie Steam, PlayStation, Xbox und Nintendo gehören ihren jeweiligen Inhabern; dieses Projekt steht mit keinem dieser Unternehmen in Verbindung.

