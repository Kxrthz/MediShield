# MediShield v1.0

MediShield is a pharmacy operations MVP built with Flask. It brings catalog and inventory management, patient records, prescription billing, local interaction screening, invoices, notifications, analytics, and exports into one workspace.

> **Clinical scope:** Interaction screening is a local demonstration aid and is not a comprehensive or patient-specific clinical reference. Confirm findings against current product information and qualified clinical judgment.

## Features

- Authenticated admin and pharmacist demo accounts with role-protected catalog actions.
- Medicine and patient CRUD APIs, stock adjustment, expiry and low-stock views.
- Billing with server-side stock/amount checks, audited admin override, and invoice PDFs.
- AI Guardian performs debounced live medicine compatibility checks through a server-side OpenAI-compatible chat API. Configure `AI_API_KEY`, `AI_API_URL`, and `AI_MODEL`; without a key, analysis is marked unavailable and acknowledgement is required before continuing.
- Dashboard metrics and six charts backed by SQLite records.
- Notifications with unread status, mark-all-read, history, and delete actions.
- Reports in CSV and PDF: daily/weekly/monthly/yearly sales, inventory, low stock, expiry, interactions, patient purchases, top sellers, payment methods, categories, and revenue by day.
- Grouped workspace search, accessibility preferences, dark theme, compact mode, custom error views, and searchable help/about pages.
- Backup center for SQLite and CSV downloads, plus validated medicine/patient CSV imports.
- Inventory supplier, batch, price, expiry, and stock filters with cost/selling value summaries. Invoice cancellation restores stock; refund action is explicitly a UI placeholder.

## Screenshots

Add screenshots of the dashboard, billing, inventory, and reports here when publishing the repository.

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000. SQLite is created automatically at `instance/medishield.db`; first launch seeds demo users and sample records. `instance/` and databases are excluded from Git.

### Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Admin | admin@medishield.com | Admin@123 |
| Pharmacist | pharmacist@medishield.com | Pharma@123 |

Copy `.env.example` to `.env` for local configuration; MediShield loads values from `.env` without overriding variables already set in the environment. Keep `.env` private and out of Git. Set a strong `SECRET_KEY` and replace demo credentials before exposing the service. `COOKIE_SECURE=true` enables secure-only session cookies behind HTTPS.

## Deploy to Render

Push the repository to GitHub, then create a Blueprint using `render.yaml`. The blueprint installs requirements and starts `gunicorn app:app`. It generates `SECRET_KEY` and unique seeded account passwords, and sets secure cookies. Retrieve the generated `ADMIN_PASSWORD` from the Render service environment to sign in as the demo administrator. The default SQLite database path is under `instance/`; Render free instances have ephemeral storage, so this deployment is for demo use. The `render.yaml` includes comments for attaching a paid persistent disk at `/opt/render/project/src/instance`; verify the mount path and point `DATABASE_URL` at that location. For a public production service, use managed PostgreSQL and configure its connection string.

## GitHub

Create a repository, add this project, and push the default branch. Keep `.env`, databases, and runtime credentials out of commits.

## Project structure

```text
MediShield/
├── app.py                 # Flask app setup, startup, and sample data
├── config.py              # Environment-based application settings
├── extensions.py          # SQLAlchemy and Flask-Login
├── models/                # Users, medicines, patients, bills, notifications
├── routes/                # Authentication, management, billing, reports APIs
├── utils/                 # Interaction screening and PDF generation
├── database/              # Incremental demo data seeders
├── templates/             # Shared layout and application pages
├── static/                # CSS and JavaScript
├── instance/              # Auto-created local SQLite database (ignored)
├── requirements.txt
├── Procfile
├── runtime.txt
└── render.yaml
```

## Roadmap

- Replace sample interaction content with a maintained, licensed, clinically curated source and governance process.
- Use persistent managed storage, backups, and production-grade account provisioning.
- Add paginated audit exports and automated deployment checks.

## License

No license has been assigned yet. Add a license file before redistributing.


### AI Guardian configuration and limits

Set the Google Gemini API key only on the server (`AI_API_KEY`); it is never sent to the browser. MediShield defaults to Gemini's OpenAI-compatible chat-completions endpoint and `gemini-3.8-flash`; `AI_API_URL` and `AI_MODEL` can be changed for another compatible provider. Checks are cached briefly in process memory and are not written as standalone analysis records; completed invoices retain their AI status, confidence, and findings for invoice/PDF history. Medicine labels and limited patient context (age, gender, allergies, and notes) are sent to Gemini; avoid putting patient-identifying details in notes and review provider data-retention terms before using real patient information.

AI Guardian is a screening aid, not validated clinical decision support. Model confidence is not a clinical probability. Verify alerts and uncertain results against authoritative sources and pharmacist judgment. FDA guidance emphasizes that healthcare professionals should be able to independently review the basis for clinical decision-support recommendations: [FDA Clinical Decision Support Software](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software).
