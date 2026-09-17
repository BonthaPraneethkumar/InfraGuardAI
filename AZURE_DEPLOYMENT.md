# Azure production direction

The local one-day MVP deliberately uses SQLite and local file storage so it is easy to run.

For a production Microsoft/Azure implementation, replace the local components with:

- **Azure App Service or Azure Container Apps** — host the FastAPI application.
- **Azure Blob Storage** — complaint and resolution evidence.
- **Azure Database for PostgreSQL** — durable case/workflow data.
- **Azure Maps** — map visualization, geocoding and infrastructure hotspots.
- **Microsoft Entra External ID** — citizen/officer authentication and role separation.
- **Azure Monitor + Application Insights** — telemetry, errors and performance.
- **Azure Key Vault** — store Sarvam and other API secrets.

Do not deploy the current unauthenticated officer dashboard as a production government system.
Add identity, authorization, audit logs, encryption, retention rules and a production-grade
PII/image safety service first.
