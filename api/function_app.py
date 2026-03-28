import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import azure.functions as func
from cryptography.fernet import Fernet

app = func.FunctionApp()
logger = logging.getLogger(__name__)

# Coarse in-memory rate limit (resets on cold start)
_rate_limit: dict[str, list[float]] = {}
EDGE_RATE_LIMIT = 3
EDGE_RATE_WINDOW = 86400  # 24 hours

PROFANITY_BLOCKLIST = {"fuck", "shit", "ass", "bitch", "nigger", "faggot", "cunt", "kike", "spic"}
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


def _get_user_id(req: func.HttpRequest) -> str | None:
    """Extract userId from Azure SWA client principal header."""
    principal = req.headers.get("x-ms-client-principal")
    if not principal:
        return None
    try:
        decoded = json.loads(base64.b64decode(principal))
        return decoded.get("userId")
    except (json.JSONDecodeError, ValueError):
        return None


def _check_edge_rate_limit(user_id: str) -> bool:
    """Coarse in-memory rate limit. Returns True if allowed."""
    now = time.time()
    timestamps = _rate_limit.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < EDGE_RATE_WINDOW]
    _rate_limit[user_id] = timestamps
    return len(timestamps) < EDGE_RATE_LIMIT


def _record_request(user_id: str) -> None:
    _rate_limit.setdefault(user_id, []).append(time.time())


def _validate_text(text: str) -> str | None:
    """Validate suggestion text. Returns error message or None if valid."""
    if not text or len(text.strip()) < 10:
        return "Suggestion must be at least 10 characters."
    if len(text) > 300:
        return "Suggestion must be under 300 characters."
    if URL_PATTERN.search(text):
        return "URLs are not allowed in suggestions."
    words = set(text.lower().split())
    if words & PROFANITY_BLOCKLIST:
        return "Please keep suggestions respectful."
    return None


def _trigger_workflow(source: str, text: str, submitted_at: str, submitter_encrypted: str) -> bool:
    """Trigger the ingest-suggestion workflow via GitHub API."""
    import urllib.request

    token = os.environ.get("GITHUB_PAT", "")
    repo = os.environ.get("GITHUB_REPO", "")
    if not token or not repo:
        logger.error("GITHUB_PAT or GITHUB_REPO not configured")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/ingest-suggestion.yml/dispatches"
    payload = json.dumps({
        "ref": "main",
        "inputs": {
            "source": source,
            "text": text,
            "submitted_at": submitted_at,
            "submitter_encrypted": submitter_encrypted,
        },
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status == 204
    except Exception as e:
        logger.error("Failed to trigger workflow: %s", e)
        return False


@app.function_name("suggest")
@app.route(route="suggest", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def suggest(req: func.HttpRequest) -> func.HttpResponse:
    user_id = _get_user_id(req)
    if not user_id:
        return func.HttpResponse(
            json.dumps({"ok": False, "message": "Authentication required."}),
            status_code=401,
            mimetype="application/json",
        )

    if not _check_edge_rate_limit(user_id):
        return func.HttpResponse(
            json.dumps({"ok": False, "message": "Too many suggestions. Please try again later."}),
            status_code=429,
            mimetype="application/json",
        )

    try:
        body = req.get_json()
        text = body.get("suggestion", "").strip()
    except (ValueError, AttributeError):
        return func.HttpResponse(
            json.dumps({"ok": False, "message": "Invalid request body."}),
            status_code=400,
            mimetype="application/json",
        )

    error = _validate_text(text)
    if error:
        return func.HttpResponse(
            json.dumps({"ok": False, "message": error}),
            status_code=400,
            mimetype="application/json",
        )

    key = os.environ.get("SUGGESTION_ENCRYPTION_KEY", "")
    if not key:
        logger.error("SUGGESTION_ENCRYPTION_KEY not configured")
        return func.HttpResponse(
            json.dumps({"ok": False, "message": "Server configuration error."}),
            status_code=500,
            mimetype="application/json",
        )

    f = Fernet(key.encode())
    submitter_encrypted = f.encrypt(user_id.encode()).decode()
    submitted_at = datetime.now(timezone.utc).isoformat()

    if not _trigger_workflow("web", text, submitted_at, submitter_encrypted):
        return func.HttpResponse(
            json.dumps({"ok": False, "message": "Failed to submit suggestion. Please try again."}),
            status_code=500,
            mimetype="application/json",
        )

    _record_request(user_id)

    return func.HttpResponse(
        json.dumps({"ok": True, "message": "Thank you! Your suggestion has been received."}),
        status_code=200,
        mimetype="application/json",
    )
