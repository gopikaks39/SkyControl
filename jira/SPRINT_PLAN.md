# SkyControl sprint plan (Scrum, 2-week sprints)

47 user stories in 9 epics, 205 story points over 6 sprints (average velocity 34 points per sprint). Import `skycontrol_jira_import.csv` into Jira (see `docs/JIRA_GUIDE.md`).
Sprints 1-5 are imported as Done (the delivered increment); Sprint 6 is imported as To Do so it can be run live on the Jira board.

| Sprint | Dates | Goal | Points |
|---|---|---|---|
| SKY Sprint 1 | 2026-08-03 to 2026-08-14 | Secure login portal, project skeleton and real data ingestion | 25 |
| SKY Sprint 2 | 2026-08-17 to 2026-08-28 | Operations management and surveillance-integrity analytics | 26 |
| SKY Sprint 3 | 2026-08-31 to 2026-09-11 | AI models: learned trajectory prediction, conflict probe, holding, anomaly detection | 32 |
| SKY Sprint 4 | 2026-09-14 to 2026-09-25 | Communication safety, context-switch policy and the scenario engine | 47 |
| SKY Sprint 5 | 2026-09-28 to 2026-10-09 | 3D web app: airspace replay, scenario lab, statistics and emergency injection | 43 |
| SKY Sprint 6 | 2026-10-12 to 2026-10-23 | DevOps (Docker, Jenkins, GitHub Actions), testing, report and release | 32 |

## Epics

| Epic | Title | Points |
|---|---|---|
| E1 | Secure login portal and user management | 17 |
| E2 | Real data pipeline (OpenSky recording) | 13 |
| E3 | Operations management | 15 |
| E4 | Real-data analytics and statistics | 34 |
| E5 | AI models and adaptive automation | 34 |
| E6 | Scenario lab (21 step-by-step scenarios) | 32 |
| E7 | 3D web application and UX | 27 |
| E8 | DevOps and quality | 23 |
| E9 | Documentation, report and demonstration | 10 |

## SKY Sprint 1 (2026-08-03 to 2026-08-14)

Goal: Secure login portal, project skeleton and real data ingestion.

| Story | Epic | Points |
|---|---|---|
| Login with verified credentials | E1 | 5 |
| Store every login attempt in the backend | E1 | 3 |
| Lock a username after 7 failures in 15 minutes | E1 | 3 |
| Sessions, CSRF protection and logout | E1 | 3 |
| Load the London-Amsterdam OpenSky recording | E2 | 5 |
| Dataset register with provenance | E2 | 3 |
| Project skeleton, linting and test harness | E8 | 3 |

## SKY Sprint 2 (2026-08-17 to 2026-08-28)

Goal: Operations management and surveillance-integrity analytics.

| Story | Epic | Points |
|---|---|---|
| Import and live-capture OpenSky snapshots | E2 | 3 |
| Flight CRUD, search and cancellation | E3 | 5 |
| Runway allocation with conflict blocking | E3 | 5 |
| Runway calendar with alternatives | E3 | 3 |
| Priority queue and alert centre | E3 | 2 |
| Detect duplicate (ghost) targets | E4 | 5 |
| Coast dropped tracks and measure the error | E4 | 3 |

## SKY Sprint 3 (2026-08-31 to 2026-09-11)

Goal: AI models: learned trajectory prediction, conflict probe, holding, anomaly detection.

| Story | Epic | Points |
|---|---|---|
| Compare STCA-style alerting with the SkyControl probe | E4 | 8 |
| Detect holding and estimate AMAN linear holding | E4 | 5 |
| Similar callsigns sharing airspace | E4 | 3 |
| Learned trajectory predictor | E5 | 8 |
| Hold predictor (30-80 NM before the stack) | E5 | 3 |
| Emergency anomaly detector | E5 | 5 |

## SKY Sprint 4 (2026-09-14 to 2026-09-25)

Goal: Communication safety, context-switch policy and the scenario engine.

| Story | Epic | Points |
|---|---|---|
| Communication Monte Carlo with sensitivity analysis | E4 | 5 |
| Adaptive automation (context switch) policy | E5 | 5 |
| Readback verifier | E5 | 8 |
| Scenario engine with exact conflict verification | E6 | 8 |
| Communication scenarios | E6 | 5 |
| Surveillance and automation scenarios | E6 | 5 |
| Emergency and runway scenarios | E6 | 5 |
| Ten-step handling pipeline per scenario | E6 | 3 |
| Workflow model: conventional vs hybrid | E6 | 3 |

## SKY Sprint 5 (2026-09-28 to 2026-10-09)

Goal: 3D web app: airspace replay, scenario lab, statistics and emergency injection.

| Story | Epic | Points |
|---|---|---|
| Supervisor user management and attempt log page | E1 | 3 |
| Statistical analysis page | E4 | 5 |
| Emergency injection into real traffic | E5 | 5 |
| Approval gate and role rules | E6 | 3 |
| 3D airspace replay of the recording | E7 | 8 |
| Scenario lab page with step-by-step view | E7 | 8 |
| Communication assistant page | E7 | 5 |
| Command centre and gap analysis pages | E7 | 3 |
| AI models page with policy simulator | E7 | 3 |

## SKY Sprint 6 (2026-10-12 to 2026-10-23)

Goal: DevOps (Docker, Jenkins, GitHub Actions), testing, report and release.

| Story | Epic | Points |
|---|---|---|
| OpenSky multi-frame recorder script | E2 | 2 |
| Automated test suite | E8 | 5 |
| Multi-stage Dockerfile and compose | E8 | 5 |
| Jenkins pipeline | E8 | 5 |
| GitHub repository and Actions CI | E8 | 3 |
| Smoke and load tests | E8 | 2 |
| Project report (VIT template) | E9 | 5 |
| Guides: GitHub, Jenkins, Jira, Docker | E9 | 3 |
| Faculty demonstration script | E9 | 2 |

## Ceremonies

* Sprint planning (Monday, week 1): pick stories up to the team velocity, agree the sprint goal.
* Daily stand-up (15 min): yesterday, today, blockers; update the board.
* Sprint review (Friday, week 2): demonstrate the increment in the running app.
* Retrospective: what went well, what to improve, one action item.

## Definition of done

* Code on a feature branch named after the issue key, merged through a pull request.
* `ruff check .` clean and all tests green in GitHub Actions and Jenkins.
* Acceptance criteria demonstrated in the running app; docs updated.
* Jira issue moved to Done with the commit linked.
