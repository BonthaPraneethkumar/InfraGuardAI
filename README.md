# InfraGuard AI

InfraGuard AI is an AI-assisted smart-city infrastructure reporting and response platform.

## Main capabilities
- Citizen complaint interface
- Photo evidence
- Voice complaint recording
- GPS/location capture
- Privacy gate before image acceptance
- Sarvam Saaras voice-to-text integration
- Sarvam-105B complaint triage
- Issue type, severity and department recommendation
- Officer dashboard
- Registered → Assigned → In Progress → Resolved workflow
- Resolution evidence
- Citizen tracking
- Analytics dashboard

## Technology
- HTML, CSS, JavaScript
- Python + FastAPI
- OpenCV
- Sarvam Saaras
- Sarvam-105B
- SQLite

## Run locally
1. Copy `.env.example` to `.env`
2. Add your Sarvam API key if available:
   `SARVAM_API_KEY=your_key_here`
3. Double-click `START_INFRAGUARD.bat`

Or:
```bash
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000`

## Public GitHub Pages demo
The public mobile interface is in `docs/index.html`.

After uploading this repository:
**Settings → Pages → Deploy from a branch → main → /docs**

Your demo URL will be:
`https://YOUR-USERNAME.github.io/InfraGuardAI/`

## Privacy note
Citizen images are not sent to Sarvam in this MVP. The OpenCV privacy gate is a hackathon prototype and should not be described as a complete production PII detector.
