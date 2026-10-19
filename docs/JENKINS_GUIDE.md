# Jenkins CI/CD pipeline for SkyControl

The `Jenkinsfile` defines a declarative pipeline with six stages:

| Stage | What happens | Fails when |
|---|---|---|
| Checkout | Gets the code from GitHub; detects whether SkyControl is the repo root or the `SkyControl/` folder | Repository/branch unreachable |
| Lint and tests | `docker build --target test` then runs `ruff check` and **93 pytest tests** inside the container; JUnit + coverage reports are copied out and published | Any lint error or failing test |
| Build image | Builds the runtime image (`skycontrol:<build>`, `:<git-sha>`, `:latest`) with the real-data analysis pre-computed | Docker build error |
| Smoke test container | Starts the new image on port 5099 and runs `scripts/smoke_test.sh`: health, frontend, **wrong credentials rejected (401)**, login, scenario plan verified, **failed attempt stored** | Any check fails |
| Deploy | Replaces the `skycontrol` container on port 5000 (database kept in the `skycontrol-db` volume) | Health check fails |
| Post actions | Archives `reports/` (junit.xml, coverage.xml) | – |

The agent only needs the **Docker CLI** and **curl**; Python runs inside containers. This pipeline was executed
successfully end to end (build 9: 93 tests passed, smoke test passed, deployed, `Finished: SUCCESS`);
the console log is in `docs/evidence/jenkins_console_build9.txt` and the JUnit file in `docs/evidence/junit_build9.xml`.

## 1. Start Jenkins (Docker Desktop, simplest)

```powershell
cd SkyControl\jenkins
docker compose up -d --build
docker exec skycontrol-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Open <http://localhost:8080>, paste the password, choose **Install suggested plugins** (includes Pipeline, Git,
JUnit, Credentials Binding, Pipeline Stage View) and create your admin user.

`jenkins/docker-compose.yml` mounts the host Docker socket and sets `SKYCONTROL_TARGET_HOST=host.docker.internal`
so the pipeline can reach the containers it starts. (Running Jenkins as root with the Docker socket is fine for
a local lab; do not do it on a shared server.)

*Already have Jenkins installed natively?* Make sure `docker` and `curl` work for the Jenkins user
(`docker ps` from a pipeline `sh` step). On Windows, a native Jenkins needs a Linux agent or WSL for `sh` steps;
the Docker setup above avoids that.

## 2. Add the two credentials

*Manage Jenkins → Credentials → System → Global credentials → Add Credentials*, kind **Secret text**:

| ID | Secret |
|---|---|
| `skycontrol-controller-password` | a password with 12+ characters, letters and digits |
| `skycontrol-supervisor-password` | another such password |

They are injected only into the smoke-test and deploy stages and are masked in the console log.

## 3. Create the pipeline job

1. *New Item* → name `SkyControl` → **Pipeline** → OK.
2. *General*: tick **GitHub project** and paste the repository URL (optional, adds a link).
3. *Build Triggers*: tick **Poll SCM** with schedule `H/5 * * * *` (checks GitHub every 5 minutes).
   For instant builds use **GitHub hook trigger for GITScm polling** and add a webhook in GitHub
   (*Settings → Webhooks → Payload URL* `http://<public-jenkins-url>/github-webhook/`). A Jenkins on your
   laptop is not reachable from GitHub, so polling is the practical choice; a tunnel such as ngrok also works.
4. *Pipeline*: **Pipeline script from SCM** → SCM **Git** → Repository URL
   `https://github.com/<you>/SkyControl.git` (add a credential with a GitHub token if the repo is private) →
   Branch `*/main` → **Script Path** `Jenkinsfile` (or `SkyControl/Jenkinsfile` inside a larger repo).
5. Save, then **Build with Parameters** → keep `DEPLOY` ticked → *Build*.

## 4. Read the results

* **Stage View** on the job page: one column per stage, green/red, with timings.
* **Test Result** (build page): 93 tests and the trend graph across builds.
* **Console Output**: full log. Look for `Smoke test passed` and `Finished: SUCCESS`.
* **Build Artifacts**: `reports/junit.xml`, `reports/coverage.xml`.
* After a green build SkyControl runs at <http://localhost:5000> (sign in with the credentials from step 2).

Screenshots to take for the report: Stage View, Test Result trend, Console Output end, Credentials page
(IDs only), job configuration (Pipeline section).

## 5. Typical failures

| Message | Fix |
|---|---|
| `permission denied ... docker.sock` | Use `jenkins/docker-compose.yml` (runs as root), or add the jenkins user to the `docker` group |
| `Could not find credentials entry with ID` | Create both secret-text credentials with exactly the IDs above |
| `curl: (7) Failed to connect ... 5099` | Jenkins in Docker: set `SKYCONTROL_TARGET_HOST=host.docker.internal` (already in the compose file) |
| `port is already allocated` (5000) | Stop whatever uses port 5000 or change `APP_PORT` in the Jenkinsfile |
| Tests fail | Open *Test Result*; run `python -m pytest -x` locally with the same commit |

## 6. How the pipeline fits the DevOps cycle

```
Jira issue (SKY-n) → branch feature/SKY-n → commits → pull request → GitHub Actions checks
      → merge to main → Jenkins: lint + tests → image → smoke test → deploy → feedback in Jira
```
