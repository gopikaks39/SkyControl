# SkyControl: hybrid AI-assisted air traffic management lab

SkyControl shows how artificial intelligence can **complement** today's air traffic control (ATC) by closing
known gaps (voice readback errors, similar callsigns, late or noisy conflict alerts, untrusted surveillance,
low-level holding and emergency workload), while keeping the human controller in command through explicit
**context switches** between automation levels.

Everything is built and measured on a **real 90-minute OpenSky recording of London–Amsterdam traffic**
(906 aircraft, 86,447 position reports). Emergencies are simulated on top of that real traffic, and 21
step-by-step scenarios compare conventional ATC with the SkyControl hybrid.

> Academic simulation and analysis tool. Not certified, not for operational air traffic control.

## What is inside

| Area | What you can show |
|---|---|
| Login portal | Verified credentials (PBKDF2), "Wrong username or password" with remaining attempts, every attempt stored with IP, browser and reason, 15-minute lockout after 7 failures |
| 3D airspace | Real recorded traffic in 3D with trails, predicted conflicts, similar callsigns, holding, duplicate (ghost) targets, 5-minute learned predictions; inject an emergency on any real aircraft and watch the hybrid response |
| Scenario lab | 21 scenarios (communication, separation, surveillance, automation, emergency, runway, weather, capacity), each with a 10-step pipeline, approval gate, context-switch log, readback verification and conventional-vs-SkyControl comparison |
| Communication assistant | Structured clearance, ICAO phraseology, readback verification (typed or speech), similar-callsign warnings |
| Statistical analysis | Measured results on the real recording, modelled comparisons with sensitivity analysis, scenario benchmark; paired Wilcoxon tests and bootstrap CIs |
| AI models | Learned trajectory predictor, hold predictor, anomaly detector, readback verifier, context-switch simulator |
| Operations | Flights, runways, runway calendar, priority queue, alerts, incident reports |
| Security & audit | Login-attempt log, user management, audit trail |

Headline results (real data unless marked): 5-minute trajectory error −34.5% on held-out traffic;
medium-term conflict alerts −72% vs a naive probe at the same 5-minute horizon; dropped-track position error
6.24 → 1.48 NM; 21 duplicate-target pairs found; 10 similar-callsign pairs sharing airspace; 268 aircraft-minutes
of holding, about half absorbable en route (modelled); undetected communication errors −91% (modelled).
See `docs/GAP_ANALYSIS.md` and the Statistical analysis page.

## Quick start (Windows, VS Code)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

On first launch you choose the `controller` and `supervisor` passwords (12+ characters, letters and digits).
Open **http://127.0.0.1:5000**. The first start analyses the recording (about one minute, then cached).
Or double-click `start_windows.bat`. Linux/macOS: `sh start_linux_mac.sh`.

## Docker

```bash
cp .env.example .env        # set SKYCONTROL_CONTROLLER_PASSWORD and SKYCONTROL_SUPERVISOR_PASSWORD
docker compose up -d --build
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check .
python -m pytest            # 93 tests, ~2 minutes (builds the real-data analysis once)
```

## Guides

| Guide | Purpose |
|---|---|
| `START_HERE.md` | Five-minute setup and faculty demo script |
| `docs/GAP_ANALYSIS.md` | Gaps in current ATC, the fixes and the evidence |
| `docs/ARCHITECTURE.md` | Components, data flow, algorithms |
| `docs/GITHUB_GUIDE.md` | Push the project to GitHub, branches, pull requests |
| `docs/JENKINS_GUIDE.md` | Jenkins CI/CD pipeline (validated run in `docs/evidence/`) |
| `docs/JIRA_GUIDE.md` | Scrum project, sprints and CSV import (`jira/`) |
| `docs/DOCKER_GUIDE.md` | Build, run, update and back up with Docker |
| `docs/report/` | Project report in the VIT template (`.docx` to edit, `.pdf` to read) |

## Data and honesty rules

* `data/london_amsterdam_opensky.json.gz`: real OpenSky recording (provenance and SHA-256 in the app).
  Derived speed/heading/vertical rate are estimates; fuel, emergencies and clearances are not in ADS-B.
* Scenario trajectories, emergencies and hazards are constructed and labelled as such.
* Every statistic is labelled **measured on real data**, **modelled** (with its assumptions and a sensitivity
  analysis) or **scenario**. Nothing is presented as an operational safety claim.
