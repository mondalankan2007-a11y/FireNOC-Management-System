# FireNOC-Management-System 🚒

A centralized web application for **Fire Department Inspection & No Objection Certificate (NOC) Management**, streamlining the issuance of fire safety clearance for buildings, offices, and institutions.

---

## 📖 Project Overview

The **FireNOC Management System** digitizes the lifecycle of fire safety compliance:
1. **Application:** Building owners/representatives apply online for a Fire NOC and submit required architectural & fire safety documentation.
2. **Verification & Scheduling:** The fire department audits submissions and schedules an on-site physical inspection.
3. **Inspection & Reporting:** Fire officers inspect site preparedness, log safety equipment parameters, and flag any deficiencies.
4. **Certification:** Upon fulfilling all fire hazard mitigation requirements, administrators issue an authorized digital Fire NOC certificate.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | HTML5, CSS3, Bootstrap 5, JavaScript |
| **Backend** | Python 3, Django |
| **Database** | PostgreSQL |
| **Version Control** | Git & GitHub |

---

## 👥 Team Members & Responsibilities

| Member | Module / Role | Primary Responsibilities |
|---|---|---|
| **Ankan** | **Applicant Module** | Building profile registration, NOC application submission, fire safety document uploads, and application tracking status. |
| **Aditya** | **Fire Officer / Inspection Module** | Officer dashboard, physical site inspection scheduling, safety checklist audits, deficiency recording, and report submission. |
| **Harsh** | **Admin + Database + NOC Module** | System administration, database schema design & migrations, NOC approval workflow, digital certificate generation, and audit logging. |

---

## 🧩 Planned Modules

### 1. Common Foundation *(Initialized)*
- Shared Bootstrap responsive layout (`base.html`), navigation, and footer.
- Centralized template, static, and media directory configuration.
- Environment-driven configuration via `.env` (`python-dotenv`).
- PostgreSQL database settings via `psycopg2-binary`.

### 2. Applicant Module (`applicants/`)
- User account registration & login for applicants.
- Multi-step Fire NOC application form (building dimensions, occupancy classification, hazard level).
- Fire safety document upload (blueprints, hydrant plans, equipment test certificates).
- Application tracking dashboard.

### 3. Officer / Inspection Module (`inspections/` or `officers/`)
- Inspection assignment queue for designated fire officers.
- Digital checklist for fire extinguishers, emergency exits, hose reels, alarms, and smoke vents.
- Deficiency / non-compliance report generation with re-inspection triggers.

### 4. Admin & NOC Generation Module (`admin_noc/`)
- Department executive dashboard with analytics on pending and cleared applications.
- Approval/rejection workflow engine.
- Tamper-proof Fire NOC certificate issuance with unique identification numbers.

---

## 📁 Project Directory Structure

```text
FireNOC-Management-System/
├── config/                 # Project configuration directory
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py         # Database, templates, static & media settings
│   ├── urls.py             # Root URL routing
│   ├── views.py            # Landing page view
│   └── wsgi.py
├── applicants/             # Applicant app
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py           # (To be implemented by Ankan)
│   ├── tests.py
│   ├── urls.py             # Routes for /applicant/
│   └── views.py            # Placeholder view: "Applicant Module Coming Soon"
├── templates/              # Global HTML templates
│   ├── base.html           # Common Bootstrap master layout
│   ├── home.html           # Landing page extending base.html
│   └── applicants/
│       └── home.html       # Applicant placeholder page
├── static/                 # Static assets (CSS, JS, images)
│   ├── css/
│   │   └── style.css       # Project stylesheet
│   └── js/
│       └── main.js         # Global JavaScript
├── media/                  # Upload directory (tracked via .gitkeep)
│   └── .gitkeep
├── manage.py               # Django management script
├── requirements.txt        # Minimal required dependencies
├── .env.example            # Sample environment variables template
├── .gitignore              # Files excluded from git tracking
└── README.md               # Project documentation
```

---

## 🚀 Getting Started

Follow these steps to set up and run the project locally on your machine:

### 1. Clone the Repository
```bash
git clone https://github.com/mondalankan2007-a11y/FireNOC-Management-System.git
cd FireNOC-Management-System
```

### 2. Create and Activate a Virtual Environment
- **macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```
- **Windows:**
  ```bash
  python -m venv venv
  venv\Scripts\activate
  ```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```
Update your database credentials in `.env` to match your local PostgreSQL configuration:
```ini
DB_ENGINE=django.db.backends.postgresql
DB_NAME=firenoc_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

### 5. Verify the System Setup
```bash
python manage.py check
```

### 6. Start the Development Server
```bash
python manage.py runserver
```
Visit the following URLs in your browser:
- Landing Page: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- Applicant Portal: [http://127.0.0.1:8000/applicant/](http://127.0.0.1:8000/applicant/)

