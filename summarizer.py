# summarizer.py
from __future__ import annotations

import re
from typing import Any, Dict, List


MAX_LOW_PRIORITY = 8


# ======================
# Helpers (safe fields)
# ======================

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _safe_subject(e: Dict[str, Any]) -> str:
    return _norm(e.get("subject") or e.get("Subject") or "")


def _safe_from(e: Dict[str, Any]) -> str:
    return _norm(e.get("from") or e.get("From") or "")


def _safe_snippet(e: Dict[str, Any]) -> str:
    return _norm(
        e.get("snippet")
        or e.get("snippetText")
        or e.get("preview")
        or ""
    )


# ======================
# Dedupe repeated alerts
# ======================

def _compact_key(subject: str, sender: str) -> str:
    base = f"{subject}||{sender}".lower()
    base = re.sub(r"\b[a-f0-9]{6,}\b", "<hash>", base)
    base = re.sub(r"\b\d{4,}\b", "<num>", base)
    return base.strip()


# ======================
# Classification rules
# ======================

INFRA_SENDERS = [
    "render",
    "railway",
    "github",
    "cloudflare",
    "aws",
    "google cloud",
    "gcp",
    "uptimerobot",
]


INCIDENT_KEYWORDS = [
    "deployment crashed",
    "server failure detected",
    "crashed",
    "exited with status",
    "health check",
    "outage",
    "incident",
    "downtime",
    "failed",
    "error",
]


PROMO_KEYWORDS = [
    "off",
    "desconto",
    "promo",
    "newsletter",
    "final call",
    "últimas horas",
    "sale",
]


def _is_google_alert(sender: str, subject: str) -> bool:
    t = f"{sender} {subject}".lower()
    return "google alerts" in t or "alerta do google" in t


def _looks_like_incident(subject: str, sender: str, snippet: str) -> bool:
    text = f"{subject} {sender} {snippet}".lower()

    is_infra_sender = any(s in text for s in INFRA_SENDERS)

    # evita alertas genéricos
    if "alert" in text and not is_infra_sender:
        return False

    return any(k in text for k in INCIDENT_KEYWORDS)


def _is_recovery(subject: str, snippet: str) -> bool:
    t = f"{subject} {snippet}".lower()
    return any(k in t for k in ["recovered", "is live", "healthy", "resolved", "back up"])


def _priority_bucket(subject: str, sender: str, snippet: str) -> str:
    if _is_google_alert(sender, subject):
        return "MEDIA"

    if _looks_like_incident(subject, sender, snippet) and not _is_recovery(subject, snippet):
        return "ALTA"

    if _looks_like_incident(subject, sender, snippet) and _is_recovery(subject, snippet):
        return "MEDIA"

    text = f"{subject} {snippet}".lower()
    if any(k in text for k in PROMO_KEYWORDS):
        return "BAIXA"

    return "BAIXA"


# ======================
# Output helpers
# ======================

def _one_line(subject: str, snippet: str) -> str:
    if snippet:
        return _norm(snippet)[:140]
    return subject


def _actions(bucket: str) -> List[str]:
    if bucket == "ALTA":
        return [
            "Abrir o dashboard do serviço e checar logs agora.",
            "Se for erro após deploy, fazer rollback para versão estável.",
            "Tentar restart/redeploy; se persistir, analisar stack trace.",
        ]
    if bucket == "MEDIA":
        return [
            "Confirmar status saudável no dashboard.",
            "Monitorar por 30–60 minutos.",
        ]
    return ["Arquivar ou mover para newsletters/promos."]


# ======================
# Main summarizer
# ======================

def build_summary(emails: List[Dict[str, Any]]) -> str:
    if not emails:
        return "Nenhum email encontrado."

    grouped: Dict[str, Dict[str, Any]] = {}

    for e in emails:
        subject = _safe_subject(e)
        sender = _safe_from(e)
        snippet = _safe_snippet(e)

        key = _compact_key(subject, sender)

        if key not in grouped:
            grouped[key] = {
                "subject": subject,
                "from": sender,
                "snippet": snippet,
                "count": 1,
            }
        else:
            grouped[key]["count"] += 1
            if len(snippet) > len(grouped[key]["snippet"]):
                grouped[key]["snippet"] = snippet

    items = list(grouped.values())

    high, medium, low = [], [], []

    for it in items:
        bucket = _priority_bucket(it["subject"], it["from"], it["snippet"])
        it["bucket"] = bucket

        if bucket == "ALTA":
            high.append(it)
        elif bucket == "MEDIA":
            medium.append(it)
        else:
            low.append(it)

    lines: List[str] = []

    if high:
        lines.append("Emails com prioridade ALTA\n")
        for i, it in enumerate(high, 1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"{i}) {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {_one_line(it['subject'], it['snippet'])}")
            lines.append("- Ações práticas:")
            for a in _actions("ALTA"):
                lines.append(f"  - {a}")
            lines.append("")

    if medium:
        lines.append("Emails com prioridade MÉDIA\n")
        for i, it in enumerate(medium, 1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"{i}) {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {_one_line(it['subject'], it['snippet'])}")
            lines.append("- Ações sugeridas:")
            for a in _actions("MEDIA"):
                lines.append(f"  - {a}")
            lines.append("")

    if low:
        lines.append("Emails de BAIXA prioridade (ação opcional)\n")
        for it in low[:MAX_LOW_PRIORITY]:
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"- {it['subject']} {tag}".strip())
            lines.append(f"  - Resumo: {_one_line(it['subject'], it['snippet'])}")

        if len(low) > MAX_LOW_PRIORITY:
            lines.append(f"\n(+ {len(low) - MAX_LOW_PRIORITY} emails omitidos)")

    return "\n".join(lines).strip()
