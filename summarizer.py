from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_EMAILS_TO_SEND = int(os.getenv("MAX_EMAILS_TO_SEND", "40"))


# ==========
# Heurísticas locais (antes do LLM)
# ==========

TECH_ALERT_KEYWORDS = [
    "render", "railway", "deployment", "crashed", "server failure", "incident", "downtime",
    "uptime", "statuspage", "monitoring", "error rate", "latency",
    "kubernetes", "pod", "container", "healthcheck", "cpu", "memory",
]
TECH_SENDER_PATTERNS = [
    r"@render\.com",
    r"@railway\.app",
    r"@statuspage\.io",
    r"@pagerduty\.com",
    r"@datadoghq\.com",
    r"@uptimerobot\.com",
    r"@sentry\.io",
]

HIGH_INTENT_KEYWORDS = [
    # banco / pagamentos / cobranças / prazos
    "banco", "itau", "itaú", "bradesco", "santander", "nubank", "caixa", "bb", "banco do brasil",
    "boleto", "fatura", "cobrança", "cobranca", "pagamento", "venc", "vence", "vencimento",
    "atraso", "pendente", "débito", "debito", "inadimpl", "juros", "multa", "pix",
    "cartão", "cartao", "estorno", "reembolso", "chargeback", "comprovante", "extrato",
    "renovação", "renovacao", "assinatura", "plano",
    "iptu", "ipva", "condomínio", "condominio", "aluguel", "energia", "luz", "água", "agua",
    "internet", "telefone", "plano de saúde", "plano de saude",
    # escola
    "escola", "colégio", "colegio", "mensalidade", "rematrícula", "rematricula",
    "matrícula", "matricula", "boletim", "prova", "reunião", "reuniao", "material",
    # compras (pode envolver cobrança/prazo)
    "pedido confirmado", "pedido", "compra", "nota fiscal", "entrega", "rastreio", "rastreamento",
    # “associação/cadastro falhou” pode ser dinheiro/serviço
    "associação", "associacao", "não foi realizada", "nao foi realizada", "recusado", "recusada",
]

LOW_LIKELY_TOPICS = [
    # promo/newsletter/social
    "newsletter", "promo", "desconto", "oferta", "últimas horas", "ultima chance", "final call",
    "tiktok", "strava", "vans",
]


def build_summary(emails: List[Dict[str, Any]]) -> str:
    normalized = [_normalize_email(e) for e in (emails or [])][:MAX_EMAILS_TO_SEND]
    if not normalized:
        return "Nenhum email encontrado."

    for e in normalized:
        e["_tech_alert"] = _looks_like_tech_alert(e)

    # Tenta LLM (com tom humano)
    items = _classify_with_llm(normalized)
    if items:
        return _format_summary(items)

    # Fallback (sem LLM)
    items_fb = [_fallback_item(e) for e in normalized]
    return _format_summary(items_fb)


def _normalize_email(e: Dict[str, Any]) -> Dict[str, Any]:
    subject = (e.get("subject") or "").strip() or "(sem assunto)"
    sender = (e.get("from") or e.get("sender") or "").strip() or "(remetente desconhecido)"
    snippet = (e.get("snippet") or e.get("body") or "").strip()

    dt = e.get("date") or e.get("internalDate") or e.get("internal_date")
    iso_date = _to_iso(dt)

    return {
        "id": e.get("id") or "",
        "subject": subject,
        "from": sender,
        "snippet": snippet[:800],
        "date": iso_date,
    }


def _to_iso(dt: Any) -> str:
    try:
        if dt is None:
            return ""
        if isinstance(dt, (int, float)):
            if dt > 10_000_000_000:  # ms
                dt = dt / 1000.0
            return datetime.fromtimestamp(dt).isoformat()
        if isinstance(dt, str):
            return dt
    except Exception:
        pass
    return ""


def _looks_like_tech_alert(e: Dict[str, Any]) -> bool:
    sender = (e.get("from") or "").lower()
    text = f"{e.get('subject','')} {e.get('from','')} {e.get('snippet','')}".lower()

    for pat in TECH_SENDER_PATTERNS:
        if re.search(pat, sender):
            return True

    return any(kw in text for kw in TECH_ALERT_KEYWORDS)


# ==========
# LLM
# ==========

def _classify_with_llm(emails: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "Você é um assistente humano do Leandro, responsável por triagem de emails.\n"
        "TOM: escreva de forma natural, direta e útil — como um assistente pessoal.\n"
        "Sem linguagem robótica. Nada de 'sem sinais fortes'.\n\n"
        "OBJETIVO: priorizar banco/contas/escola/prazos. Alertas técnicos não importam.\n\n"
        "REGRAS FORTES:\n"
        "1) Se o email for alerta técnico (Render/Railway/deployment/incident/status/monitoramento), "
        "sempre BAIXA prioridade e score <= 20, mesmo repetido.\n"
        "2) ALTA prioridade quando houver dinheiro/pagamento/cobrança/vencimento/renovação, "
        "assunto de escola, ou prazo explícito.\n"
        "3) MÉDIA quando for relevante mas sem ação clara imediata.\n"
        "4) BAIXA para promoções/newsletters/social ou coisas que podem ser ignoradas.\n\n"
        "Para cada item gere:\n"
        "- score (0–100)\n"
        "- bucket: ALTA | MÉDIA | BAIXA\n"
        "- one_liner: 1–2 frases humanas dizendo (a) o tema e (b) por que importa ou por que pode ignorar.\n"
        "- actions: 1–3 ações práticas curtas, apenas se fizer sentido.\n\n"
        "Responda APENAS em JSON no formato:\n"
        "{ \"items\": [ {\"subject\":\"...\",\"score\":90,\"bucket\":\"ALTA\",\"one_liner\":\"...\",\"actions\":[\"...\"]} ] }\n"
    )

    payload_emails = []
    for e in emails:
        payload_emails.append({
            "subject": e.get("subject", ""),
            "from": e.get("from", ""),
            "date": e.get("date", ""),
            "snippet": e.get("snippet", ""),
            "tech_alert": bool(e.get("_tech_alert")),
        })

    user_prompt = "Classifique estes emails:\n" + json.dumps(payload_emails, ensure_ascii=False)

    try:
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
    except Exception:
        return None

    try:
        data = json.loads(_extract_json(text))
        items = data.get("items", [])
        if not isinstance(items, list):
            return None

        cleaned = []
        for it in items:
            subj = str(it.get("subject", "")).strip() or "(sem assunto)"
            score = int(it.get("score", 0))
            score = max(0, min(100, score))

            bucket = str(it.get("bucket", "")).strip().upper()
            bucket = _bucket_from_score(score)  # força coerência

            one = str(it.get("one_liner", "")).strip()
            if not one:
                # se vier vazio, cria um tema humano no fallback
                one = _infer_topic_line({"subject": subj, "from": "", "snippet": ""})

            actions = it.get("actions", [])
            if not isinstance(actions, list):
                actions = []
            actions = [str(a).strip() for a in actions if str(a).strip()][:3]

            # segurança: se for tech_alert, rebaixa
            if _looks_like_tech_alert({"subject": subj, "from": "", "snippet": one}):
                score = min(score, 20)
                bucket = "BAIXA"

            cleaned.append({
                "subject": subj,
                "score": score,
                "bucket": bucket,
                "one_liner": one,
                "actions": actions,
            })

        # ordena
        cleaned.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
        return cleaned

    except Exception:
        return None


def _extract_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


# ==========
# Fallback (sem LLM)
# ==========

def _fallback_item(e: Dict[str, Any]) -> Dict[str, Any]:
    subject = e.get("subject", "(sem assunto)")
    text = f"{e.get('subject','')} {e.get('from','')} {e.get('snippet','')}".lower()

    if e.get("_tech_alert"):
        score = 10
        bucket = "BAIXA"
        one = "Isso é um alerta técnico automático (infra/serviço). Pode ignorar."
        actions = []
        return {"subject": subject, "score": score, "bucket": bucket, "one_liner": one, "actions": actions}

    hits = sum(1 for kw in HIGH_INTENT_KEYWORDS if kw in text)

    if hits >= 2:
        score = 85
        bucket = "ALTA"
        one = "Isso parece envolver dinheiro/prazo (cobrança, vencimento, renovação ou algo a resolver). Eu abriria."
        actions = [
            "Abrir o email e identificar valor/prazo.",
            "Resolver agora (pagar/renovar/responder) se fizer sentido.",
        ]
    elif hits == 1:
        score = 55
        bucket = "MÉDIA"
        one = "Pode ser algo relevante (conta, compra, escola ou prazo), mas não está explícito. Vale uma olhada rápida."
        actions = ["Abrir e decidir se vira pendência."]
    else:
        score = 25
        bucket = "BAIXA"
        one = _infer_topic_line(e)
        actions = []

    return {"subject": subject, "score": score, "bucket": bucket, "one_liner": one, "actions": actions}


def _infer_topic_line(e: Dict[str, Any]) -> str:
    subject = (e.get("subject") or "").strip()
    sender = (e.get("from") or "").strip()
    text = f"{subject} {e.get('snippet','')}".lower()

    if any(k in text for k in ["pedido", "compra", "confirmad", "nota fiscal", "entrega", "rastre"]):
        return "Parece ser sobre compra/entrega (confirmação ou atualização). Dá pra ignorar se você já estiver ciente."
    if any(k in text for k in ["newsletter", "manchetes", "braziljournal", "news", "alerta do google", "google alerts"]):
        return "Isso é conteúdo informativo/newsletter (pra ler quando tiver tempo)."
    if any(k in text for k in ["desconto", "promo", "oferta", "off", "últimas horas", "final call"]):
        return "É promoção/marketing. Pode arquivar sem culpa se não estiver procurando isso."
    if any(k in text for k in ["notion", "projeto", "re:", "meeting", "call"]):
        return "Parece algo de trabalho/projeto. Se não for urgente, dá pra deixar para revisar depois."
    if sender:
        return f"Email geral de {sender}: se não te puxar a atenção, pode arquivar."
    return "Email geral: não parece exigir ação agora. Pode arquivar."


def _bucket_from_score(score: int) -> str:
    if score >= 75:
        return "ALTA"
    if score >= 45:
        return "MÉDIA"
    return "BAIXA"


# ==========
# Formatação
# ==========

def _format_summary(items: List[Dict[str, Any]]) -> str:
    high = [i for i in items if i.get("bucket") == "ALTA"]
    med = [i for i in items if i.get("bucket") == "MÉDIA"]
    low = [i for i in items if i.get("bucket") == "BAIXA"]

    lines: List[str] = []

    if high:
        lines.append("Emails com prioridade ALTA\n")
        lines.extend(_format_bucket(high, include_actions=True))

    if med:
        lines.append("\nEmails com prioridade MÉDIA\n")
        lines.extend(_format_bucket(med, include_actions=True))

    if low:
        lines.append("\nEmails de BAIXA prioridade (ação opcional)\n")
        lines.extend(_format_bucket(low, include_actions=False))

    return "\n".join(lines).strip()


def _format_bucket(bucket_items: List[Dict[str, Any]], include_actions: bool) -> List[str]:
    out: List[str] = []
    for idx, it in enumerate(bucket_items, start=1):
        score = int(it.get("score", 0))
        subj = it.get("subject", "(sem assunto)")
        one = it.get("one_liner", "").strip()

        out.append(f"{idx}) [{score}/100] {subj}")
        out.append(f"- {one}")

        if include_actions:
            actions = it.get("actions", [])
            if isinstance(actions, list) and actions:
                out.append("  Ações:")
                for a in actions[:3]:
                    out.append(f"  - {a}")

        out.append("")  # linha em branco
    if out and out[-1] == "":
        out.pop()
    return out
