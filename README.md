# EBMS — Electronic Bid Management System

> A secure, PPRA-compliant procurement management platform for Botswana's public sector.

![Python](https://img.shields.io/badge/Python-3.13-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?style=flat-square&logo=flask)
![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Branch](https://img.shields.io/badge/Branch-feature%2Fui--redesign-orange?style=flat-square)

---

## 📋 Overview

**EBMS** (Electronic Bid Management System) is a full-stack web application built with Flask that digitises and secures the public procurement lifecycle in Botswana. It enforces PPRA Act compliance throughout every stage — from tender creation to award publication — while providing role-segregated dashboards for all stakeholders.

Key capabilities include **end-to-end encrypted bid submission** (Fernet cryptography), **dual-envelope support**, **evaluation committee workflows**, and a **real-time operational reporting** module.

---

## ✨ Features

| Module | Description |
|---|---|
| 🏛️ **Procurement Management** | Create, publish, and manage tenders (works, services, consultancy, supplies) |
| 🔒 **Encrypted Bid Submission** | Bidder documents encrypted at upload with Fernet keys; never stored in plaintext |
| 📬 **Dual Envelope Support** | Separate Technical and Financial envelopes, opened under committee quorum |
| 📋 **Evaluation Workflows** | Pass/Fail, Scored, Weighted, Least Cost, and Quality & Cost evaluation methods |
| 👥 **Role-Based Access Control** | Procurement Unit, Committee Chair/Secretary, Evaluator, User Department, Bidder, Admin |
| 📢 **Clarifications & Addenda** | Anonymous question submission; approved clarifications published publicly |
| 🔔 **Notification System** | Real-time in-app alerts with read/unread state management |
| 📊 **Operational Reports** | Live KPI snapshot — open tenders, submission counts, compliance indicators |
| 🛡️ **Audit Trail** | Full action logging for compliance and PPRA accountability |
| ⚙️ **Admin Panel** | User management, site settings, and PPRA configuration parameters |

---

## 🗂️ Project Structure

```
BACK/
├── ebms_flask/
│   └── ebms_flask/
│       ├── app/
│       │   ├── models/          # SQLAlchemy ORM models
│       │   │   ├── user.py      # User & role management
│       │   │   ├── procurement.py
│       │   │   ├── bidder.py
│       │   │   ├── submission.py
│       │   │   ├── evaluation.py
│       │   │   ├── committee.py
│       │   │   ├── award.py
│       │   │   ├── complaint.py
│       │   │   ├── notification.py
│       │   │   ├── communication.py
│       │   │   ├── audit.py
│       │   │   └── site_setting.py
│       │   ├── routes/          # Flask blueprints
│       │   │   ├── auth.py      # Login, register, password reset
│       │   │   ├── dashboard.py
│       │   │   ├── procurements.py
│       │   │   ├── evaluations.py
│       │   │   ├── bidders.py
│       │   │   ├── notifications.py
│       │   │   ├── reports.py
│       │   │   └── admin.py
│       │   ├── templates/       # Jinja2 HTML templates (18 files)
│       │   ├── static/          # styles.css — Premium bocra-ui design system
│       │   ├── utils/           # Encryption, helpers, seed scripts
│       │   ├── extensions.py    # Flask extensions (SQLAlchemy, Login, etc.)
│       │   └── __init__.py      # App factory
│       └── run.py               # Entry point
├── .agents/                     # AI agent skills (bocra-ui, callab-ui, etc.)
├── requirements.txt
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/AllenMachona/BACK.git
cd BACK

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r ebms_flask/requirements.txt

# 4. Set environment variables
# Create a .env file or export directly:
# SECRET_KEY=<your-secret-key>
# FERNET_KEY=<your-fernet-key>   # generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 5. Initialise the database and seed demo data
cd ebms_flask
python -m ebms_flask.app.utils.seed   # (if available)

# 6. Run the development server
python -m flask --app ebms_flask.run run --debug
```

The app will be available at **http://localhost:5000**

---

## 🔑 Default Roles & Access

| Role | Access Level |
|---|---|
| `admin` | Full system access, user management, site settings |
| `procurement_unit` | Create & manage tenders, move procurement through workflow stages |
| `committee_chair` | Approve evaluation reports, open envelopes |
| `committee_secretary` | Manage committee meetings and minutes |
| `evaluator` | Score and evaluate submitted bids |
| `user_department` | Request procurements, track tender progress |
| `bidder` | Register, access bidder workspace, submit encrypted bids |

---

## 🔐 Security

- Bid documents are encrypted using **Fernet symmetric encryption** (from the `cryptography` library) at the moment of upload.
- Passwords are hashed using **Werkzeug** (`pbkdf2:sha256`).
- Session management is handled by **Flask-Login** with `remember_me` token support.
- Password reset uses **time-limited secure tokens**.
- All sensitive configuration (secret keys, Fernet keys) is managed via environment variables — never hardcoded.

---

## 🎨 UI Design System

The frontend uses a custom **premium CSS design system** (`styles.css`) inspired by the `bocra-ui` and `callab-ui` design tokens:

- **Typography:** Plus Jakarta Sans + Inter (Google Fonts)
- **Palette:** PPRA Navy `#0f172a` · Accent Blue `#2563eb` · Gold `#d97706`
- **Components:** Bento stat cards, responsive table wrappers, status badge pills, glassmorphism navbar, premium auth split-panel layout
- **Responsive:** Mobile-first, sidebar collapses on ≤768px, all tables have horizontal scroll containers

---

## 📦 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, Flask 3.x |
| ORM | SQLAlchemy + Flask-SQLAlchemy |
| Auth | Flask-Login, Werkzeug |
| Encryption | cryptography (Fernet) |
| Database | SQLite (dev) |
| Frontend | Vanilla HTML/CSS/JS, Bootstrap Icons |
| Version Control | Git — feature branch workflow |

---

## 🌿 Branch Strategy

All development follows a **feature branch workflow**:

- `main` — stable, production-ready code
- `feature/ui-redesign` — current active branch (premium UI overhaul)

> ⚠️ We never commit directly to `main`. Each file change is an individual standalone commit on a feature branch, then merged via Pull Request.

---

## 📄 License

This project is licensed under the **MIT License**.

---

*Built for the Botswana PPRA compliance ecosystem · EBMS v1.0*