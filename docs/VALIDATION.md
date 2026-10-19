# Validation record

What was verified for SkyControl 6.0.0, how, and what was not.

## Automated tests (pytest)

93 tests in `tests/`, all passing locally and inside the Jenkins pipeline (build 9, `docs/evidence/`).
Statement coverage of `backend/`: 90% (`docs/evidence/coverage_build9.xml`).

| File | Tests | Covers |
|---|---|---|
| `test_auth.py` | 9 | Wrong password / unknown user give the same message; every attempt stored with reason, IP, browser; no passwords stored; lockout after 7; CSRF; roles; user management; password change; logout |
| `test_operations.py` | 6 | Flight CRUD and validation, runway conflicts raise alerts, calendar alternatives, priority queue, alerts and incident reports, dashboard |
| `test_scenarios.py` | 47 | All 21 scenarios verified conflict-free; comparator shows the problem in 20; ten-step pipeline; context-switch levels; readback and callsign scenarios; fuel deadline |
| `test_lab_api.py` | 5 | Supervisor gate for critical plans, controller consent, AUTO runs, replay controls, override reason, recording and managed sources |
| `test_comms_and_automation.py` | 10 | Readback verifier (correct, mismatch, wrong aircraft, incomplete, dropped digit, NATO letters, runway), phraseology, callsign similarity, automation policy, exact conflict geometry, visibility graph, comms API |
| `test_analytics.py` | 12 | Recording integrity (906 aircraft, 353 frames, 708 duplicates removed), known ghost pair, coasting, predictor on held-out data, alert reduction, holding stacks, BAW425/BAW725 pair, communication model, anomaly detection, emergency injection and its API |
| `test_app.py` | 4 | Health, static frontend, security headers, dataset register, audit access |

Run: `python -m pytest` (about 2 minutes; the real-data analysis is built once per session).

## Lint

`ruff check .` (pyflakes rules and syntax errors): clean.

## Browser checks (headless Chromium, Playwright)

All 14 pages load without JavaScript errors; WebGL 3D views render (SwiftShader). Interactive flows exercised:
wrong login shows the attempt counter; critical plan blocked for a controller and approved after switching to
supervisor (run kept); readback-error scenario reaches all ten steps; emergency injection on a real aircraft;
readback check returns MISMATCH; all eight statistics tabs render. Screenshots are in the project report.
Not done: manual testing on physical GPUs, Safari, or touch devices.

## Container and pipeline

* `docker build` (multi-stage) succeeded; the runtime container became healthy; `scripts/smoke_test.sh` passed
  (health, frontend, wrong credentials 401, login, scenario verified, failed attempt stored).
* The `Jenkinsfile` ran end to end in Jenkins (jenkinsfile-runner with the Pipeline, JUnit and Credentials
  Binding plugins): Checkout, Lint and tests (93 passed), Build image, Smoke test, Deploy, `Finished: SUCCESS`.
  In this sandbox the image build needed the sandbox's proxy certificate added to a local copy of the
  Dockerfile; the shipped Dockerfile needs no change on a normal network.
* GitHub Actions workflow `.github/workflows/ci.yml` was written but not executed here (no GitHub runner).

## Performance (local, 4 vCPU, 8 concurrent clients, 120 requests per endpoint)

| Endpoint | p50 ms | p95 ms |
|---|---|---|
| health | 18 | 27 |
| dashboard | 50 | 75 |
| flights | 48 | 70 |
| airspace frame (cached per frame; first call computes) | 23 | 2537 |
| gaps | 24 | 32 |
| scenario create | 343 | 385 |
| readback verify | 40 | 62 |

The full real-data analysis takes about 45 s once and is cached (and pre-computed inside the Docker image).

## Known limits

* One 90-minute recording of one region; learned models must be retrained and re-validated elsewhere.
* The 8 real encounters are too few for strong statements about warning time (p = 0.125).
* Communication results are modelled from literature-informed assumptions (sensitivity analysis provided); the
  readback verifier was evaluated on generated transcripts, not real ASR output.
* The cleared level used by the intent-aware probe is approximated from the next level-off in the recording.
* Scenario workflow timings are modelled task times, not observed controller performance.
* No MFA; SQLite is single-node. Not operational ATC software.
