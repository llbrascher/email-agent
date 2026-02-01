# gmail_client.py
import os
import json
from typing import List, Dict, Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Ajuste seus scopes aqui (tem que bater com o token.json)
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _load_credentials_from_env() -> Credentials:
    """
    Carrega credenciais a partir da variável de ambiente GMAIL_TOKEN_JSON
    (conteúdo inteiro do token.json).
    """
    token_json = os.environ.get("GMAIL_TOKEN_JSON")
    if not token_json:
        raise RuntimeError(
            "Missing env var GMAIL_TOKEN_JSON. Put the full token.json content there."
        )

    try:
        info = json.loads(token_json)
    except json.JSONDecodeError as e:
        raise RuntimeError("GMAIL_TOKEN_JSON is not valid JSON.") from e

    creds = Credentials.from_authorized_user_info(info, SCOPES)

    # Se expirou e tiver refresh_token, renova automaticamente
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def get_gmail_service():
    creds = _load_credentials_from_env()

    if not creds or not creds.valid:
        # Se não tem refresh_token, não tem como renovar no servidor
        if not creds.refresh_token:
            raise RuntimeError(
                "GMAIL_TOKEN_JSON has no refresh_token. "
                "You must re-generate token.json with offline access."
            )
        raise RuntimeError("Gmail credentials invalid even after refresh attempt.")

    return build("gmail", "v1", credentials=creds)


def list_recent_emails(max_results: int = 5) -> List[Dict[str, Any]]:
    service = get_gmail_service()

    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = results.get("messages", [])

    emails = []
    for m in messages:
        msg = service.users().messages().get(userId="me", id=m["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        emails.append(
            {
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
            }
        )

    return emails
