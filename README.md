# cheongdo-hackathon-2026

## Backend API

Azure demo: **[다녀왔어요 앱](https://dayat-echo-20261105-150954.azurewebsites.net)** · [OpenAPI](https://dayat-echo-20261105-150954.azurewebsites.net/docs) · [Health](https://dayat-echo-20261105-150954.azurewebsites.net/healthz)

The Azure App Service is Linux/Python 3.12 in Korea Central on a Basic B1 plan. **The current deployment is returning 503**: Azure startup logs show `ModuleNotFoundError: No module named 'app'`, and the deployed site root is missing the `app` directory. The plan is running, but the web app is not yet healthy. It is an unauthenticated hackathon demo intended for **synthetic data only**. State is in memory and resets when the app restarts. It does not persist records or provide production security. Do not send real personal or health data.

Run locally with Python 3.12 or later:

```powershell
cd backend
py -3 -m pip install -r requirements-dev.txt
py -3 -m uvicorn app.main:app --reload
```

The app home page is a responsive, dependency-free web UI served by FastAPI. It covers the synthetic visit dashboard, participant consent and confirmation, recording-state controls, transcript review, AI draft review/approval, case context, visit-order adjustments, and follow-up task creation/completion. Recording controls demonstrate workflow state only: browser microphone capture and speech recognition are not implemented.

`GET /api/v1/dashboard` returns the synthetic schedule and tasks. Other `/api/v1` routes cover cases, schedule reorder, task edits, participant consent (with confirmation timestamps), recording-state transitions, transcript review, draft streaming, and explicit approval. The draft request contains only a visit ID; the server selects the bundled synthetic transcript, so callers cannot submit arbitrary text. The recording endpoints simulate workflow state; browser microphone capture and speech recognition are not implemented.

Draft generation uses Microsoft Agent Framework's `GitHubCopilotAgent` integration with the GitHub Copilot SDK, a transcript-evidence tool, SSE streaming, schema validation, and exact-quote verification. It requires an installed, authenticated GitHub Copilot CLI runtime. The current Azure runtime reports `copilot_cli_available: false`, so draft generation responds with a visible `503` until that runtime is configured; it never substitutes a fake AI result. Azure CLI is used for deployment and does not provide Copilot model authentication.

To redeploy the API, use an Azure CLI login and run `.\deploy.ps1` from `backend`. The script targets the same App Service resource group and app.