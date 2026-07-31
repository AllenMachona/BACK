# EBMS — Electronic Bid Management System (Flask edition)

A real Flask + SQLAlchemy backend behind the static PPRA-styled mockup —
every page now renders from live database queries. Nothing in the templates
is hardcoded; the demo data you see comes entirely from `seed.py`, which you
can inspect, edit, or delete.

## What changed from the static mockup

- **Real authentication** — `flask-login`, password hashing (`werkzeug`),
  account lockout after 5 failed attempts, audit-logged login/logout.
- **Real data model** — 13 SQLAlchemy models (Role, User, Procurement, Lot,
  Bidder, Submission, CommitteeMember, EvaluationCriteria, Evaluation,
  ScoreSheet, Award, Complaint, Communication, AuditLog, Notification),
  matching the SOAR requirements document's structure.
- **Real workflow enforcement** — procurement status transitions follow an
  explicit legal-move map (`app/routes/procurements.py: TRANSITIONS`),
  cancellation requires a reason, submission deadlines are enforced
  server-side (late attempts are rejected and audit-logged, not just hidden
  in the UI).
- **Real encryption at rest** — bid files are encrypted with Fernet
  (`app/utils/crypto.py`) the moment they're uploaded; nothing is stored as
  plaintext.
- **Real notifications** — in-app `Notification` rows plus best-effort
  email (falls back to printing to the console if SMTP isn't configured).
- **Append-only audit log** — every material action writes an `AuditLog`
  row; no route updates or deletes one.
- **Role-based access control** — every route is decorated with either
  `@role_required(...)` or `@permission_required(...)`, checked against the
  `Role` table's permission flags, not hardcoded role name strings scattered
  through the code.

## Known, honest limitation

I built and syntax-checked every file in this project, and cross-verified
every `url_for()` call against actual route names and every template
variable against what its route actually passes in. What I could **not** do
is install the dependencies and click through the running app myself — this
sandbox has no network access to `pip install flask-sqlalchemy` etc. So:
run `pip install -r requirements.txt`, then `python seed.py`, then
`python run.py`, and if anything throws an error on the very first run,
paste it back to me — it's likely a small one (a typo or an edge case
static analysis can't catch), not a structural problem.

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env`:
- Generate `SUBMISSION_ENCRYPTION_KEY`:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- Generate a real `SECRET_KEY` (anything long and random).
- Leave `DATABASE_URL` blank to use a local SQLite file (zero setup), or
  point it at Postgres for anything beyond a demo.

```bash
python seed.py     # creates roles, demo users, two demo procurements
python run.py       # starts on http://localhost:5000
```

### Demo accounts (all share the password `ChangeMe123!`)

| Username | Role |
|---|---|
| `admin` | System Administrator |
| `j.molefe` | Accounting Officer |
| `s.kgosi` | Procurement Oversight |
| `d.tlou` | Procurement Unit |
| `g.motsumi` | Committee Secretary |
| `p.seleka` / `p.seleka2` | Opening Panel |
| `k.motsumi` | Committee Chair |
| `n.kgosi` | Evaluator |
| `bidder1` | Bidder (Mokwena Construction) |

**Change or remove these before any real deployment.**

### Suggested walkthrough

1. Log in as `d.tlou` (Procurement Unit) — see `TB-2026-089`, already seeded
   in `submission_open` status.
2. Log in as `bidder1` in another browser/incognito window, open the
   workspace, and submit a bid (any small file works — it'll be encrypted
   on upload).
3. Back as `d.tlou`, advance the procurement through its lifecycle using
   the "Advance" button on the detail page.
4. Log in as `k.motsumi` (Committee Chair) or `n.kgosi` (Evaluator) and
   open `/evaluations` — `TB-2026-086` is pre-seeded with real committee
   members, submissions, and scores so the scoring matrix has genuine data
   to show immediately.
5. Log in as `admin` to see `/admin/users` and `/reports/operational`,
   all computed from the live database.

## What's still out of scope (same honesty as the Node version)

- Live integrations to Botswana's National eProcurement System, PPRA
  Contractor Register, CIPA, or BURS — these need credentials from those
  bodies, not code.
- A cryptographic quorum/HSM scheme for bid opening (this version doesn't
  yet implement the multi-person opening-quorum control the Node version
  had — that's a good next addition if you want it).
- Penetration testing, WCAG accessibility audit, load testing.
- MFA flow (the `mfa_enabled`/`mfa_secret` columns exist on `User` but no
  TOTP flow is wired up yet).

## Project structure

```
ebms_flask/
  app/
    __init__.py        app factory
    extensions.py       db, login_manager, migrate
    models/             one file per entity
    routes/              one blueprint per area
    templates/           Jinja2, extending base.html
    static/styles.css
    utils/
      crypto.py          Fernet encryption for submissions
      audit.py            log_action() — append-only audit log
      decorators.py        role_required / permission_required
      notify.py             notification + email dispatch
  config.py
  run.py
  seed.py
  requirements.txt
  .env.example
```
