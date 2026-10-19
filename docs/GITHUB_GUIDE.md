# Pushing SkyControl to GitHub

This guide uses Windows PowerShell in VS Code. Linux/macOS commands are the same except for paths.

## 0. One-time setup

1. Install Git: <https://git-scm.com/download/win> (accept the defaults).
2. Tell Git who you are (use the e-mail of your GitHub account):

```powershell
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```

3. Sign in to GitHub. The first `git push` opens a browser window (Git Credential Manager). If your college
   network blocks it, create a **Personal Access Token** (GitHub → Settings → Developer settings → Personal
   access tokens → Fine-grained → *Contents: Read and write*) and paste it when Git asks for a password.

## 1. Option A: SkyControl as its own repository (recommended)

1. On GitHub: **New repository** → name `SkyControl` → *Private* or *Public* → do **not** add a README,
   .gitignore or licence (the project already has them) → **Create repository**.
2. In the extracted `SkyControl` folder:

```powershell
cd C:\path\to\SkyControl
git init
git add .
git status                      # check: no .env, no .venv, no data\skycontrol.sqlite3 in the list
git commit -m "SKY-1 Initial SkyControl hybrid ATM lab"
git remote add origin https://github.com/<your-user>/SkyControl.git
git push -u origin main
```

`.gitignore` already excludes `.venv`, `.env`, caches and the SQLite database. **Never commit `.env`**: it holds
passwords. The 2.4 MB recording `data/london_amsterdam_opensky.json.gz` is meant to be committed.

## 2. Option B: inside an existing repository (e.g. `agileassesment_06`)

```powershell
git clone https://github.com/<your-user>/agileassesment_06.git
cd agileassesment_06
# copy the SkyControl folder here, then:
git checkout -b feature/skycontrol
git add SkyControl
git commit -m "SKY-1 Add SkyControl hybrid ATM lab"
git push -u origin feature/skycontrol
```

Open a pull request on GitHub (*Compare & pull request*), review it, then merge into `main`.
In Jenkins set **Script Path** to `SkyControl/Jenkinsfile` (the pipeline detects the sub-folder itself).

## 3. Day-to-day workflow (feature branches + pull requests)

```powershell
git checkout main
git pull
git checkout -b feature/SKY-23-readback-verifier
# ... edit, then run the checks locally:
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
git add -A
git commit -m "SKY-23 Treat dropped digits as 'confirm' instead of mismatch"
git push -u origin feature/SKY-23-readback-verifier
```

Then open a pull request into `main`. Good habits for the assessment:

* Put the **Jira issue key** (e.g. `SKY-23`) at the start of every commit message and branch name. With the
  *GitHub for Jira* app installed, the commits, branches and pull requests appear on the Jira issue
  (see `docs/JIRA_GUIDE.md`).
* Small commits with clear messages; one feature per branch.
* Protect `main`: GitHub → Settings → Branches → *Add rule* → `main` → *Require a pull request* and
  *Require status checks to pass* (select **SkyControl CI / test**).

## 4. Continuous integration on GitHub

`.github/workflows/ci.yml` runs automatically on every push and pull request:

1. `ruff check .` (lint)
2. `pytest` (93 tests, JUnit report uploaded as an artifact)
3. `docker build` and a container smoke test (wrong login rejected, failed attempt stored, login, scenario).

See the **Actions** tab. Jenkins (`docs/JENKINS_GUIDE.md`) runs the same checks plus deployment.

## 5. Tag a release for submission

```powershell
git checkout main
git pull
git tag -a v6.0.0 -m "SkyControl v6.0.0 - final submission"
git push origin v6.0.0
```

On GitHub: **Releases** → *Draft a new release* → choose `v6.0.0` → attach the zip and the report → *Publish*.

## 6. Common problems

| Problem | Fix |
|---|---|
| `rejected ... fetch first` | Someone pushed first: `git pull --rebase` then `git push` |
| Authentication failed | Use a Personal Access Token as the password, or sign in again via the browser prompt |
| `.env` was committed by mistake | `git rm --cached .env`, commit, push, then **change both passwords** |
| Large file warning | Only the recording (2.4 MB) is large; do not commit `data/cache` or `*.sqlite3` |
