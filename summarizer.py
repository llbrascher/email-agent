# summarizer.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ====== Config (ajuste se quiser) ======
MAX_LOW_PRIORITY = 8  # quantos "baixa prioridade" mostrar no resumo


# ====== Util ======
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _safe_snippet(email: Dict[str, Any]) -> str:
    # Alguns retornos vêm como 'snippet', outros não. Evita KeyError.
    return _norm(
        email.get("snippet")
        or email.get("snippetText")
        or email.get("preview")
        or email.get("body_preview")
        or ""
    )


def _safe_subject(email: Dict[str, Any]) -> str:
    return _norm(email.get("subject") or email.get("Subject") or "")


def _safe_from(email: Dict[str, Any]) -> str:
    return _norm(email.get("from") or email.get("From") or email.get("sender") or "")


def _compact_key(subject: str, sender: str) -> str:
    # chave para agrupar notificações repetidas (Render/Railway etc.)
    # Remove ids variáveis e números longos que mudam a cada email.
    base = f"{subject}||{sender}".lower()
    base = re.sub(r"\b[a-f0-9]{6,}\b", "<hex>", base)          # commits/hashes
    base = re.sub(r"\b\d{4,}\b", "<num>", base)               # números longos
    base = re.sub(r"\binstance\b.*?$", "instance <x>", base)  # "Instance failed: 6b25d" etc.
    return base.strip()


def _looks_like_incident(subject: str, sender: str, snippet: str) -> bool:
    text = f"{subject} {sender} {snippet}".lower()
    keywords = [
        "failed", "failure", "crash", "crashed", "error",
        "deployment crashed", "server failure", "down",
        "incident", "alert", "health check", "exited with status",
    ]
    return any(k in text for k in keywords)


def _is_recovery(subject: str, snippet: str) -> bool:
    text = f"{subject} {snippet}".lower()
    return any(k in text for k in ["recovered", "is live", "back up", "healthy", "resolved"])


def _priority_bucket(subject: str, sender: str, snippet: str) -> str:
    """
    Retorna: 'ALTA', 'MEDIA', 'BAIXA'
    """
    text = f"{subject} {sender} {snippet}".lower()

    # Se é email de alerta e NÃO é recuperação => alta
    if _looks_like_incident(subject, sender, snippet) and not _is_recovery(subject, snippet):
        return "ALTA"

    # Alertas mas dizendo que recuperou => média
    if _looks_like_incident(subject, sender, snippet) and _is_recovery(subject, snippet):
        return "MEDIA"

    # Promos/newsletters => baixa
    promo = ["off", "desconto", "promo", "newsletter", "final call", "últimas horas", "sale"]
    if any(k in text for k in promo):
        return "BAIXA"

    # padrão
    return "BAIXA"


def _one_line_summary(subject: str, snippet: str) -> str:
    if snippet:
        # pega só um pedacinho pra não ficar enorme
        return _norm(snippet)[:140]
    return subject


def _actions_for(bucket: str, sender: str, subject: str) -> List[str]:
    # Ações genéricas (sem inventar demais)
    if bucket == "ALTA":
        return [
            "Abrir o dashboard do provedor e checar logs do deploy/worker agora.",
            "Se for regressão de release: fazer rollback para a última versão estável.",
            "Tentar restart/redeploy; se repetir, investigar stack trace e variáveis de ambiente.",
        ]
    if bucket == "MEDIA":
        return [
            "Confirmar no dashboard se está saudável (logs e métricas).",
            "Monitorar por 30–60 min para garantir que não está flapping.",
        ]
    return [
        "Arquivar ou mover para uma pasta/label (promo/newsletter).",
    ]


# ====== Core ======
def build_summary(emails: List[Dict[str, Any]]) -> str:
    """
    Espera uma lista de dicts com campos tipo:
    - subject / from / snippet (ou variações)
    """

    if not emails:
        return "Nenhum email encontrado."

    # 1) Normaliza e agrupa repetidos
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
            # mantém o snippet "mais informativo"
            if len(snippet) > len(grouped[key]["snippet"]):
                grouped[key]["snippet"] = snippet

    items = list(grouped.values())

    # 2) Classifica prioridade
    high: List[Dict[str, Any]] = []
    medium: List[Dict[str, Any]] = []
    low: List[Dict[str, Any]] = []

    for it in items:
        bucket = _priority_bucket(it["subject"], it["from"], it["snippet"])
        it["bucket"] = bucket
        if bucket == "ALTA":
            high.append(it)
        elif bucket == "MEDIA":
            medium.append(it)
        else:
            low.append(it)

    # 3) Monta texto final
    lines: List[str] = []

    if high:
        lines.append("Emails com prioridade ALTA\n")
        for idx, it in enumerate(high, start=1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            one = _one_line_summary(it["subject"], it["snippet"])
            lines.append(f"{idx}) {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {one}")
            lines.append("- Ações práticas:")
            for a in _actions_for("ALTA", it["from"], it["subject"]):
                lines.append(f"  - {a}")
            lines.append("")  # blank line

    if medium:
        lines.append("Emails com prioridade MÉDIA\n")
        for idx, it in enumerate(medium, start=1):
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            one = _one_line_summary(it["subject"], it["snippet"])
            lines.append(f"{idx}) {it['subject']} {tag}".strip())
            lines.append(f"- Resumo (1 linha): {one}")
            lines.append("- Ações sugeridas:")
            for a in _actions_for("MEDIA", it["from"], it["subject"]):
                lines.append(f"  - {a}")
            lines.append("")

    if low:
        lines.append("Emails de BAIXA prioridade (ação opcional)\n")
        for it in low[:MAX_LOW_PRIORITY]:
            tag = f"(recebido {it['count']}x)" if it["count"] > 1 else ""
            one = _one_line_summary(it["subject"], it["snippet"])
            lines.append(f"- {it['subject']} {tag}".strip())
            lines.append(f"  - Resumo: {one}")
        if len(low) > MAX_LOW_PRIORITY:
            lines.append(f"\n(+ {len(low) - MAX_LOW_PRIORITY} emails de baixa prioridade omitidos)")

    return "\n".join(lines).strip()
