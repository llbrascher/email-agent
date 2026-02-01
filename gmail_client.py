from __future__ import annotations
from typing import List, Dict
import os
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def _get_header(headers: List[Dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def list_recent_emails(hours_back: int = 6, max_results: int = 10) -> List[Dict]:
    service = get_gmail_service()

    now_utc = datetime.now(timezone.utc)
    after = now_utc - timedelta(hours=hours_back)
    after_unix = int(after.timestamp())

    query = f"after:{after_unix} -category:promotions -category:social"

    resp = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results
    ).execute()

    msgs = resp.get("messages", [])
    emails = []

    for m in msgs:
        msg = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        emails.append({
            "id": m["id"],
            "date": _get_header(headers, "Date"),
            "from": _get_header(headers, "From"),
            "subject": _get_header(headers, "Subject"),
            "snippet": msg.get("snippet", ""),
        })

    return emails