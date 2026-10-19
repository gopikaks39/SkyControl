# Deploying SkyControl with Docker

## Requirements

Docker Desktop (Windows/macOS) or Docker Engine with the compose plugin (Linux). Check with
`docker version` and `docker compose version`.

## 1. Configure

```powershell
cd SkyControl
copy .env.example .env      # Linux/macOS: cp .env.example .env
notepad .env                # set SKYCONTROL_CONTROLLER_PASSWORD and SKYCONTROL_SUPERVISOR_PASSWORD
```

Passwords need 12+ characters with letters and digits. They are used only the first time, when the
database has no accounts yet.

## 2. Build and run

```powershell
docker compose up -d --build
docker compose ps           # STATUS should become "healthy"
docker compose logs -f      # Ctrl+C to stop following
```

Open <http://localhost:5000>. The image already contains the pre-computed real-data analysis, so the
app is ready in a few seconds. The build itself takes 2–3 minutes (dependencies + analysis).

What the image contains (multi-stage `Dockerfile`):

| Stage | Purpose |
|---|---|
| `base` | Python 3.12 slim, dependencies, application code and data |
| `test` | Adds pytest/ruff and the tests; `docker build --target test` then `docker run` runs lint + tests |
| `runtime` (default) | Pre-computes the analysis, runs as an unprivileged user, health check on `/api/health`, database on the `skycontrol-db` volume |

## 3. Everyday commands

| Task | Command |
|---|---|
| Stop | `docker compose down` (data kept in the volume) |
| Update after `git pull` | `docker compose up -d --build` |
| Run the tests in Docker | `docker build --target test -t skycontrol-test . && docker run --rm skycontrol-test` |
| Smoke test | `sh scripts/smoke_test.sh http://localhost:5000 supervisor <password>` |
| Back up the database | `docker run --rm -v skycontrol_skycontrol-db:/db -v ${PWD}:/backup alpine tar czf /backup/skycontrol-db.tgz -C /db .` |
| Reset everything (deletes accounts and history) | `docker compose down -v` |

Volume names get the compose project prefix (`skycontrol_skycontrol-db`); check with `docker volume ls`.

## 4. Without compose

```powershell
docker build -t skycontrol .
docker run -d --name skycontrol -p 5000:5000 -v skycontrol-db:/app/data/db `
  -e SKYCONTROL_CONTROLLER_PASSWORD=... -e SKYCONTROL_SUPERVISOR_PASSWORD=... skycontrol
```

Interactive first-run account creation also works: `docker run -it --rm -p 5000:5000 skycontrol`
(no password variables) asks for both passwords in the terminal.

## 5. Notes for a shared or cloud deployment

* Put HTTPS in front (reverse proxy) and set `SKYCONTROL_HTTPS=1` so cookies are marked `Secure` and HSTS is sent.
* SQLite suits one container. Several replicas would need a server database.
* Live OpenSky capture needs outbound access to `opensky-network.org`; the bundled recording works offline.
* Validated here: the image built, the container became healthy, and the smoke test passed (also inside the Jenkins run).
