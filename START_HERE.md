# Start here

## 1. Run it (choose one)

**Windows (VS Code):** open the `SkyControl` folder, then double-click `start_windows.bat`
(or run the three commands in `README.md`). Choose the two passwords when asked.

**Docker:** copy `.env.example` to `.env`, fill in both passwords, then `docker compose up -d --build`.

Open **http://127.0.0.1:5000** in Chrome or Edge. Leave the terminal open. On the very first start the app
analyses the real recording for about a minute (the side bar shows "Analysing the recording…").

Requirements: Python 3.12 (3.11+ works) or Docker Desktop. No Node.js needed.

## 2. Ten-minute faculty demonstration

1. **Login portal.** Type a wrong password: the page says *Wrong username or password · N attempts left* and
   records it. Sign in as `supervisor`.
2. **Command centre.** Headline results from the real recording and the gap-to-fix table.
3. **ATC gaps & fixes.** Nine gaps (G1–G9) with today's practice, SkyControl's fix and the evidence.
4. **3D airspace (real traffic).** Press Play at 15×. Turn on *5-min predictions* to compare straight-line
   (grey) and learned (teal) predictions. Watch red predicted conflicts, amber similar callsigns, orange holds and
   violet duplicate targets. Click an aircraft above FL200 and run *Medical emergency*: the response lists
   suitable airports, the conflicts with real traffic and their resolutions, drafted messages and the
   conventional-vs-hybrid timing. Approve it.
5. **Scenario lab.** Run *Readback error*: follow the 10 steps; the message log shows the wrong readback flagged
   MISMATCH and the correction. Then *Fuel emergency* as `controller`: approval is blocked (critical), switch
   account to `supervisor`, the run is kept, approve it. Try *AI disagreement* to show the switch to MANUAL.
6. **Communication assistant.** Click *Wrong aircraft answers* then *Verify*.
7. **Statistical analysis.** Summary tab, then *Conflict prediction* and *Communication*.
8. **AI models.** Move the sliders in the context-switch simulator.
9. **Security & audit.** The login-attempt log shows the wrong password from step 1.

## 3. Where things are

```
backend/        FastAPI app, auth, routes, scenario engine (core/), real-data analytics (analytics/)
frontend/       index.html, css, js (three.js 3D views, Chart.js charts vendored in frontend/vendor)
data/           real OpenSky recording, India snapshot, reference airports/stacks, airport counts CSV
tests/          93 automated tests (pytest)
scripts/        analysis build, OpenSky recorder, smoke test, load test
docs/           guides, gap analysis, architecture, validation evidence
jenkins/        local Jenkins (Docker) for the pipeline in Jenkinsfile
jira/           sprint plan and Jira CSV import
```
