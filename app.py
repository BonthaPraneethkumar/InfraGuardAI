from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image
from io import BytesIO

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
EVIDENCE_DIR = UPLOAD_DIR / "evidence"
RESOLUTION_DIR = UPLOAD_DIR / "resolution"
DB_PATH = DATA_DIR / "infraguard.db"

for folder in (DATA_DIR, EVIDENCE_DIR, RESOLUTION_DIR):
    folder.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
SARVAM_CHAT_MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b")
DEMO_MODE = os.getenv("APP_DEMO_MODE", "true").lower() == "true"
SEED_DEMO = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"

app = FastAPI(title="InfraGuard AI", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def api_key() -> str:
    return os.getenv("SARVAM_API_KEY", "").strip()


def sarvam_configured() -> bool:
    key = api_key()
    return bool(key and key != "PASTE_YOUR_KEY_HERE")


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db_connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            department TEXT NOT NULL,
            summary TEXT NOT NULL,
            reason TEXT DEFAULT '',
            confidence REAL DEFAULT 0,
            description TEXT NOT NULL,
            transcript TEXT DEFAULT '',
            location_label TEXT DEFAULT '',
            latitude REAL,
            longitude REAL,
            image_path TEXT DEFAULT '',
            resolution_image_path TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Registered',
            officer_notes TEXT DEFAULT '',
            ai_source TEXT DEFAULT '',
            is_demo INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    if SEED_DEMO:
        count = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
        if count == 0:
            seed_reports = [
                ("IG-DEMO-001", "Traffic / Parking", "Medium", "Traffic Department",
                 "Vehicle obstructing the road near Commerzone.", "Near Commerzone, Pune",
                 "Resolved", "Traffic obstruction cleared.", "demo"),
                ("IG-DEMO-002", "Garbage Waste", "Medium", "Municipal Sanitation",
                 "Garbage accumulation requires collection.", "Viman Nagar, Pune",
                 "Resolved", "Waste collection completed.", "demo"),
                ("IG-DEMO-003", "Streetlight", "Medium", "Electrical Department",
                 "Streetlight is not functioning.", "Bengaluru, Karnataka",
                 "In Progress", "Electrical team assigned.", "demo"),
                ("IG-DEMO-004", "Road Pothole", "High", "Roads Department",
                 "Large pothole affecting road safety.", "Tambaram, Chennai",
                 "Resolved", "Road patching completed.", "demo"),
                ("IG-DEMO-005", "Electric Wires", "High", "Electrical Department",
                 "Loose electrical wires reported near the road.", "Noida, Uttar Pradesh",
                 "Assigned", "Field inspection scheduled.", "demo"),
                ("IG-DEMO-006", "Water Leak", "Medium", "Water & Utilities",
                 "Water leakage reported on a public road.", "Bengaluru, Karnataka",
                 "Registered", "", "demo"),
            ]
            created = now_iso()
            for row in seed_reports:
                conn.execute(
                    """INSERT INTO reports
                    (id, issue_type, severity, department, summary, description,
                     location_label, status, officer_notes, ai_source, is_demo,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        row[0], row[1], row[2], row[3], row[4], row[4],
                        row[5], row[6], row[7], row[8], created, created
                    ),
                )
            conn.commit()
    conn.close()


@app.on_event("startup")
def startup() -> None:
    init_db()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("image_path", "resolution_image_path"):
        if data.get(key):
            data[key] = "/" + data[key].replace("\\", "/").lstrip("/")
    data["is_demo"] = bool(data.get("is_demo"))
    return data


def scan_image(data: bytes) -> dict[str, Any]:
    """Hackathon privacy gate: detects faces, full-body human-like regions and QR codes.
    It is intentionally conservative and is not a production PII detector.
    """
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "The uploaded file is not a readable image.")

    h, w = img.shape[:2]
    scale = min(1.0, 1280 / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(35, 35)
    )

    # Human-body detector. We only count higher-confidence detections to reduce false positives.
    people_count = 0
    try:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        _, weights = hog.detectMultiScale(
            img, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        people_count = sum(float(x) >= 0.55 for x in np.array(weights).flatten())
    except Exception:
        people_count = 0

    qr_count = 0
    try:
        detector = cv2.QRCodeDetector()
        ok, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ok:
            qr_count = len([x for x in decoded_info if x is not None])
        else:
            decoded, _, _ = detector.detectAndDecode(img)
            qr_count = 1 if decoded else 0
    except Exception:
        qr_count = 0

    reasons = []
    if len(faces):
        reasons.append("human face detected")
    if people_count:
        reasons.append("human figure detected")
    if qr_count:
        reasons.append("QR code detected")

    return {
        "safe": not reasons,
        "faces": int(len(faces)),
        "people": int(people_count),
        "qr_codes": int(qr_count),
        "reasons": reasons,
    }


def save_normalized_image(data: bytes, folder: Path, stem: str) -> str:
    """Strips EXIF/metadata and saves a resized JPEG."""
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
        image.thumbnail((1600, 1600))
        filename = f"{stem}.jpg"
        path = folder / filename
        image.save(path, "JPEG", quality=88, optimize=True)
        return filename
    except Exception as exc:
        raise HTTPException(400, f"Could not process image: {exc}")


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=3, max_length=3000)
    location_label: str = ""
    latitude: float | None = None
    longitude: float | None = None


class CreateReportRequest(BaseModel):
    description: str = Field(min_length=3, max_length=3000)
    transcript: str = ""
    location_label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    image_token: str
    analysis: dict[str, Any]


class UpdateReportRequest(BaseModel):
    status: str
    officer_notes: str = ""


ISSUE_DEPARTMENTS = {
    "Road Pothole": "Roads Department",
    "Streetlight": "Electrical Department",
    "Garbage Waste": "Municipal Sanitation",
    "Water Leak": "Water & Utilities",
    "Traffic / Parking": "Traffic Department",
    "Electric Wires": "Electrical Department",
    "Tree on Road": "Parks / Municipal",
    "Other": "Municipal Control Room",
}
VALID_SEVERITIES = {"Low", "Medium", "High", "Critical"}
VALID_STATUSES = {"Registered", "Assigned", "In Progress", "Resolved"}


def fallback_analysis(text: str) -> dict[str, Any]:
    t = text.lower()
    issue = "Other"
    if any(k in t for k in ("pothole", "road hole", "damaged road", "road damage")):
        issue = "Road Pothole"
    elif any(k in t for k in ("streetlight", "street light", "lamp post", "light not working")):
        issue = "Streetlight"
    elif any(k in t for k in ("garbage", "waste", "trash", "overflowing bin", "rubbish")):
        issue = "Garbage Waste"
    elif any(k in t for k in ("water leak", "leaking water", "pipe leak", "water pipe", "sewage")):
        issue = "Water Leak"
    elif any(k in t for k in ("traffic", "parking", "parked vehicle", "vehicle blocking")):
        issue = "Traffic / Parking"
    elif any(k in t for k in ("electric wire", "electrical wire", "power cable", "live wire", "loose wire")):
        issue = "Electric Wires"
    elif any(k in t for k in ("fallen tree", "tree on road", "cut tree", "tree blocking")):
        issue = "Tree on Road"

    severity = "Medium"
    if any(k in t for k in ("live wire", "fire", "bridge collapse", "severe flooding", "life threatening")):
        severity = "Critical"
    elif any(k in t for k in ("large", "danger", "dangerous", "accident", "blocking", "exposed", "major")):
        severity = "High"
    elif any(k in t for k in ("small", "minor", "slight")):
        severity = "Low"

    summary = text.strip()
    if len(summary) > 150:
        summary = summary[:147].rstrip() + "..."

    return {
        "issue_type": issue,
        "severity": severity,
        "department": ISSUE_DEPARTMENTS[issue],
        "summary": summary,
        "reason": "Rule-based fallback used because live AI was unavailable.",
        "confidence": 0.72,
        "ai_source": "local-fallback",
    }


def extract_json(content: str) -> dict[str, Any]:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
    content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def sanitize_analysis(data: dict[str, Any], source: str) -> dict[str, Any]:
    issue = str(data.get("issue_type", "Other")).strip()
    if issue not in ISSUE_DEPARTMENTS:
        issue = "Other"

    severity = str(data.get("severity", "Medium")).strip().title()
    if severity not in VALID_SEVERITIES:
        severity = "Medium"

    department = str(data.get("department") or ISSUE_DEPARTMENTS[issue]).strip()
    if not department:
        department = ISSUE_DEPARTMENTS[issue]

    try:
        confidence = float(data.get("confidence", 0.85))
    except (TypeError, ValueError):
        confidence = 0.85
    confidence = max(0.0, min(1.0, confidence))

    return {
        "issue_type": issue,
        "severity": severity,
        "department": department,
        "summary": str(data.get("summary", "")).strip()[:240],
        "reason": str(data.get("reason", "")).strip()[:320],
        "confidence": confidence,
        "ai_source": source,
    }


async def sarvam_analyze(text: str, location_label: str) -> dict[str, Any]:
    prompt = f"""
You are the triage engine for InfraGuard AI, a civic infrastructure reporting system.
Analyze the citizen complaint and return ONLY valid JSON, with no markdown.

Citizen complaint:
{text}

Reported location label:
{location_label or "Not provided"}

Allowed issue_type values:
Road Pothole
Streetlight
Garbage Waste
Water Leak
Traffic / Parking
Electric Wires
Tree on Road
Other

Allowed severity values:
Low, Medium, High, Critical

Choose the correct government department. Use these defaults:
Road Pothole -> Roads Department
Streetlight -> Electrical Department
Garbage Waste -> Municipal Sanitation
Water Leak -> Water & Utilities
Traffic / Parking -> Traffic Department
Electric Wires -> Electrical Department
Tree on Road -> Parks / Municipal
Other -> Municipal Control Room

Severity guidance:
Critical = immediate threat to life or major public safety emergency.
High = significant safety risk, major obstruction, exposed electrical danger, or likely accident risk.
Medium = service/infrastructure problem needing normal priority.
Low = minor inconvenience with limited immediate risk.

Return exactly:
{{
  "issue_type": "...",
  "severity": "...",
  "department": "...",
  "summary": "one concise sentence",
  "reason": "one concise sentence explaining the classification",
  "confidence": 0.0
}}
"""
    payload = {
        "model": SARVAM_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": "Return concise, structured civic-infrastructure triage JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 450,
    }
    headers = {
        "api-subscription-key": api_key(),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{SARVAM_BASE_URL}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = extract_json(content)
        return sanitize_analysis(data, SARVAM_CHAT_MODEL)


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "InfraGuard AI", "time": now_iso()}


@app.get("/api/config")
def config():
    return {
        "sarvam_configured": sarvam_configured(),
        "stt_model": SARVAM_STT_MODEL,
        "chat_model": SARVAM_CHAT_MODEL,
        "demo_mode": DEMO_MODE,
        "privacy_note": "Citizen images are never sent to Sarvam in this MVP.",
    }


@app.post("/api/privacy-check")
async def privacy_check(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data received.")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Image is too large. Use an image under 12 MB.")

    result = scan_image(data)
    if not result["safe"]:
        return {
            **result,
            "image_token": None,
            "message": "Image blocked by the privacy gate. Retake the photo without people or sensitive visual markers.",
        }

    token = uuid.uuid4().hex
    filename = save_normalized_image(data, EVIDENCE_DIR, token)
    return {
        **result,
        "image_token": filename,
        "message": "Privacy check passed. Image metadata was stripped and the image was accepted.",
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not sarvam_configured():
        raise HTTPException(
            503,
            "Sarvam API key is not configured. You can type the complaint manually, or add SARVAM_API_KEY to .env.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(400, "No audio received.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Audio is too large.")

    filename = file.filename or "complaint.webm"
    content_type = file.content_type or "audio/webm"
    model_candidates = [SARVAM_STT_MODEL]
    if SARVAM_STT_MODEL != "saaras:v3":
        model_candidates.append("saaras:v3")

    last_error = None
    async with httpx.AsyncClient(timeout=60) as client:
        for model in model_candidates:
            try:
                response = await client.post(
                    f"{SARVAM_BASE_URL}/speech-to-text",
                    headers={"api-subscription-key": api_key()},
                    files={"file": (filename, data, content_type)},
                    data={
                        "model": model,
                        "mode": "translate",
                        "language_code": "unknown",
                    },
                )
                response.raise_for_status()
                result = response.json()
                return {
                    "transcript": result.get("transcript", "").strip(),
                    "language_code": result.get("language_code"),
                    "model": model,
                }
            except Exception as exc:
                last_error = str(exc)

    raise HTTPException(502, f"Sarvam speech-to-text failed: {last_error}")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    text = req.text.strip()

    if sarvam_configured():
        try:
            result = await sarvam_analyze(text, req.location_label)
            return {"analysis": result, "live_ai": True}
        except Exception as exc:
            if not DEMO_MODE:
                raise HTTPException(502, f"Sarvam analysis failed: {exc}")
            fallback = fallback_analysis(text)
            fallback["reason"] = (
                "Live Sarvam analysis was unavailable, so the hackathon fallback classified this report."
            )
            return {"analysis": fallback, "live_ai": False, "warning": str(exc)}

    if DEMO_MODE:
        return {"analysis": fallback_analysis(text), "live_ai": False}

    raise HTTPException(503, "Sarvam API key is not configured.")


@app.post("/api/reports")
def create_report(req: CreateReportRequest):
    image_name = Path(req.image_token).name
    image_file = EVIDENCE_DIR / image_name
    if not image_file.exists():
        raise HTTPException(400, "The evidence image has not passed the privacy gate.")

    analysis = sanitize_analysis(req.analysis, str(req.analysis.get("ai_source", "unknown")))
    report_id = f"IG-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
    created = now_iso()
    image_rel = str(Path("uploads") / "evidence" / image_name)

    conn = db_connect()
    conn.execute(
        """INSERT INTO reports
        (id, issue_type, severity, department, summary, reason, confidence,
         description, transcript, location_label, latitude, longitude, image_path,
         status, officer_notes, ai_source, is_demo, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Registered', '', ?, 0, ?, ?)""",
        (
            report_id,
            analysis["issue_type"],
            analysis["severity"],
            analysis["department"],
            analysis["summary"] or req.description[:240],
            analysis["reason"],
            analysis["confidence"],
            req.description,
            req.transcript,
            req.location_label,
            req.latitude,
            req.longitude,
            image_rel,
            analysis["ai_source"],
            created,
            created,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return {"report": row_to_dict(row)}


@app.get("/api/reports")
def get_reports():
    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY is_demo ASC, created_at DESC"
    ).fetchall()
    conn.close()
    return {"reports": [row_to_dict(r) for r in rows]}


@app.patch("/api/reports/{report_id}")
def update_report(report_id: str, req: UpdateReportRequest):
    if req.status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid status.")
    conn = db_connect()
    exists = conn.execute("SELECT id FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "Report not found.")
    conn.execute(
        "UPDATE reports SET status = ?, officer_notes = ?, updated_at = ? WHERE id = ?",
        (req.status, req.officer_notes.strip()[:2000], now_iso(), report_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return {"report": row_to_dict(row)}


@app.post("/api/reports/{report_id}/resolution-image")
async def resolution_image(report_id: str, file: UploadFile = File(...)):
    conn = db_connect()
    exists = conn.execute("SELECT id FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "Report not found.")

    data = await file.read()
    result = scan_image(data)
    if not result["safe"]:
        conn.close()
        return {
            **result,
            "accepted": False,
            "message": "Resolution photo blocked by the privacy gate.",
        }

    filename = save_normalized_image(data, RESOLUTION_DIR, f"{report_id}-{uuid.uuid4().hex[:6]}")
    rel = str(Path("uploads") / "resolution" / filename)
    conn.execute(
        "UPDATE reports SET resolution_image_path = ?, updated_at = ? WHERE id = ?",
        (rel, now_iso(), report_id),
    )
    conn.commit()
    conn.close()
    return {**result, "accepted": True, "path": "/" + rel.replace("\\", "/")}


@app.get("/api/analytics")
def analytics():
    conn = db_connect()
    total = conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"]
    by_status = {
        row["status"]: row["c"]
        for row in conn.execute("SELECT status, COUNT(*) c FROM reports GROUP BY status").fetchall()
    }
    by_severity = {
        row["severity"]: row["c"]
        for row in conn.execute("SELECT severity, COUNT(*) c FROM reports GROUP BY severity").fetchall()
    }
    by_department = {
        row["department"]: row["c"]
        for row in conn.execute("SELECT department, COUNT(*) c FROM reports GROUP BY department ORDER BY c DESC").fetchall()
    }
    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_department": by_department,
        "resolved": by_status.get("Resolved", 0),
        "in_progress": by_status.get("In Progress", 0),
        "high_priority": by_severity.get("High", 0) + by_severity.get("Critical", 0),
    }
