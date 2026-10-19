# Running SkyControl as a Scrum project in Jira

The sprint plan is in `jira/SPRINT_PLAN.md`: 47 user stories in 9 epics, 205 story points over six
two-week sprints (3 Aug – 23 Oct 2026). `jira/skycontrol_jira_import.csv` holds the same backlog for import.
Sprints 1–5 are imported as **Done** (the delivered increment). Sprint 6 (DevOps, tests, report, release) is
imported as **To Do**, so you can run it live on the board and get genuine burndown and velocity charts.

## 1. Create the project (Jira Cloud, free plan)

1. <https://www.atlassian.com/software/jira/free> → sign up → create a site.
2. *Projects → Create project → Software development → **Scrum*** → choose **Company-managed**
   (the CSV importer can then set sprints, epics and story points) → name **SkyControl**, key **SKY**.
3. *Project settings → Features*: make sure **Sprints**, **Estimation (Story points)** and **Backlog** are on.

## 2. Create the sprints first

*Backlog → Create sprint* six times and rename them exactly:
`SKY Sprint 1` … `SKY Sprint 6` (dates and goals from `jira/SPRINT_PLAN.md`). Importing into existing sprints
by name is the most reliable way to get stories into the right sprint.

## 3. Import the backlog

1. Gear icon → **System → External system import → CSV** (you need Jira admin rights; as the site creator you have them).
2. Upload `jira/skycontrol_jira_import.csv`, encoding UTF-8, delimiter `,`.
3. Select project **SkyControl (SKY)**.
4. Map the fields:

| CSV column | Jira field |
|---|---|
| Issue Id | Issue Id |
| Parent Id | Parent Id (links stories to their epic) |
| Issue Type | Issue Type |
| Summary | Summary |
| Description | Description |
| Priority | Priority |
| Story Points | Story point estimate (or *Story Points*) |
| Sprint | Sprint |
| Labels | Labels |
| Status | Status (tick *Map field value*: Done→Done, To Do→To Do, In Progress→In Progress) |

5. *Validate* → *Begin import*. Expect 56 issues: 9 epics and 47 stories.

If the importer cannot set sprints, select all stories of one sprint in the backlog (filter by label or summary)
and drag them into the sprint. If *Parent Id* is not offered, link epics afterwards with *Bulk change → Parent*.

## 4. Run the sprint

1. *Backlog → SKY Sprint 6 → **Start sprint*** (2 weeks, goal from the plan).
2. Board columns: To Do → In Progress → In Review → Done. Move each card as the work progresses.
3. Daily stand-up: update cards and log blockers as comments.
4. Link code: name branches and start commit messages with the key, e.g.
   `git checkout -b feature/SKY-48-jenkins-pipeline` and `git commit -m "SKY-48 Add container smoke test"`.
   Install **GitHub for Jira** (*Apps → Explore apps*) and connect the GitHub organisation/user: branches,
   commits, pull requests and builds then appear in each issue's *Development* panel.
5. At the end: *Complete sprint* → the review and retrospective happen in the meeting; record one action
   item as an issue labelled `retro`.

## 5. Reports to screenshot for the report

* **Backlog** with the six sprints and story points.
* **Board** during Sprint 6.
* **Reports → Burndown chart** (Sprint 6) and **Velocity chart** (needs completed sprints).
* **Roadmap / Timeline** showing the nine epics.
* An issue with the **Development** panel showing linked commits and the Jenkins/GitHub build.

## 6. Scrum roles and ceremonies used

| Item | How we used it |
|---|---|
| Product owner | Owns the backlog order: login and data first, then analytics, scenarios, UI, DevOps |
| Scrum master | Runs the ceremonies, removes blockers (e.g. dataset access, Docker setup) |
| Team | Developers and testers; everyone writes tests for their stories |
| Sprint planning | Stories pulled up to the average velocity (~34 points) |
| Daily stand-up | 15 minutes, board updated |
| Review | Increment demonstrated in the running app |
| Retrospective | One improvement per sprint, tracked as an issue |
| Definition of done | PR merged, lint and tests green in CI/Jenkins, acceptance criteria shown, docs updated |
