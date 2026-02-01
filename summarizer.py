# summarizer.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

MAX_LOW_PRIORITY = 8

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

RECOVERY_KEYWORDS = ["recovered", "is live", "healthy", "resolved", "back up"]

PROMO_KEYWORDS = [
    "off",
    "desconto",
    "promo",
    "newsletter",
    "final call",
    "últimas horas",
    "sale",
]

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _safe_subject(e: Dict[str, Any]) -> str:
    return _norm(e.get("subject") or e.get("Subject") or "")

def _safe_from(e: Dict[str, Any]) -> str:
    return _norm(e.get("from") or e.get("From") or "")

def _safe_snippet(e: Dict[str, Any]) -> str:
    return _norm(e.get("snippet") or e.get("snippetText") or e.get("preview") or "")

def _compact_key(subject: str, sender: str) -> str:
    base = f"{subject}||{sender}".lower()
    base = re.sub(r"\b[a-f0-9]{6,}\b", "<hash>", base)
    base = re.sub(r"\b\d{4,}\b", "<num>", base)
    return base.strip()

def _is_google_alert(sender: str, subject: str) -> bool:
    t = f"{sender} {subject}".lower()
    return "google alerts" in t or "alerta do google" in t

def _is_recovery(subject: str, snippet: str) -> bool:
    t = f"{subject} {snippet}".lower()
    return any(k in t for k in RECOVERY_KEYWORDS)

def _looks_like_incident(subject: str, sender: str, snippet: str) -> bool:
    text = f"{subject} {sender} {snippet}".lower()

    is_infra_sender = any(s in text for s in INFRA_SENDERS)

    # "alert" genérico (ex.: Google Alerts) não é incidente
    if "alert" in text and not is_infra_sender:
        return False

    return any(k in text for k in INCIDENT_KEYWORDS)

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

def _one_line(subject: str, snippet: str) -> str:
    return (_norm(snippet)[:140] if snippet else subject)

def _urgency_score(subject: str, sender: str, snippet: str, count: int) -> int:
    """
    Score 0–100 (heurístico, mas consistente).
    """
    text = f"{subject} {sender} {snippet}".lower()

    score = 0

    # base por categoria
    if _looks_like_incident(subject, sender, snippet):
        score += 55
    if _is_recovery(subject, snippet):
        score -= 25  # recuperado = menos urgente
    if _is_google_alert(sender, subject):
        score += 25
    if any(k in text for k in PROMO_KEYWORDS):
        score += 5

    # sinalizadores fortes
    strong = ["server failure detected", "deployment crashed", "crashed", "outage", "down", "exited with status"]
    if any(k in text for k in strong):
        score += 20

    # remetente "infra" pesa mais
    if any(s in text for s in INFRA_SENDERS):
        score += 10

    # repetição: 3 alertas iguais é mais importante que 1
    score += min(15, (count - 1) * 5)

    # clamp
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return int(score)

def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Retorna itens deduplicados com:
      - key (para histórico)
      - subject/from/snippet/count
      - bucket
      - score (0-100)
    """
    grouped: Dict[str, Dict[str, Any]] = {}

    for e in emails:
        subject = _safe_subject(e)
        sender = _safe_from(e)
        snippet = _safe_snippet(e)

        key = _compact_key(subject, sender)

        if key not in grouped:
            grouped[key] = {"key": key, "subject": subject, "from": sender, "snippet": snippet, "count": 1}
        else:
            grouped[key]["count"] += 1
            if len(snippet) > len(grouped[key]["snippet"]):
                grouped[key]["snippet"] = snippet

    items = list(grouped.values())

    for it in items:
        it["bucket"] = _priority_bucket(it["subject"], it["from"], it["snippet"])
        it["score"] = _urgency_score(it["subject"], it["from"], it["snippet"], it["count"])

    # ordena: maior score primeiro
    items.sort(key=lambda x: x["score"], reverse=True)
    return items

def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "Nenhum email encontrado."

    high, medium, low = [], [], []
    for it in items:
        if it["bucket"] == "ALTA":
            high.append(it)
        elif it["bucket"] == "MEDIA":
            medium.append(it)
        else:
            low.append(it)

    def actions(bucket: str) -> List[str]:
        if bucket == "ALTA":
            return [
                "Abrir o dashboard do serviço e checar logs agora.",
                "Se for erro após deploy, fazer rollback para versão estável.",
                "Tentar restart/redeploy; se persistir, analisar stack trace.",
            ]
        if bucket == "MEDIA":
            return ["Ler o conteúdo e decidir encaminhamento/ação.", "Se for recorrente, criar filtro/label no Gmail."]
        return ["Arquivar ou mover para newsletters/promos."]

    lines: List[str] = []

    if high:
        lines.append("Emails com prioridade ALTA\n")
        for i, it in enumerate(high, 1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"{i}) [{it['score']}/100] {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {_one_line(it['subject'], it['snippet'])}")
            lines.append("- Ações práticas:")
            for a in actions("ALTA"):
                lines.append(f"  - {a}")
            lines.append("")

    if medium:
        lines.append("Emails com prioridade MÉDIA\n")
        for i, it in enumerate(medium, 1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"{i}) [{it['score']}/100] {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {_one_line(it['subject'], it['snippet'])}")
            lines.append("- Ações sugeridas:")
            for a in actions("MEDIA"):
                lines.append(f"  - {a}")
            lines.append("")

    if low:
        lines.append("Emails de BAIXA prioridade (ação opcional)\n")
        for it in low[:MAX_LOW_PRIORITY]:
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            lines.append(f"- [{it['score']}/100] {it['subject']} {tag}".strip())
            lines.append(f"  - Resumo: {_one_line(it['subject'], it['snippet'])}")

        if len(low) > MAX_LOW_PRIORITY:
            lines.append(f"\n(+ {len(low) - MAX_LOW_PRIORITY} emails omitidos)")

    return "\n".join(lines).strip()
