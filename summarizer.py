import re
from typing import List, Dict, Any


HIGH_INTENT_PATTERNS = [
    r"\bvenc(e|imento|er)\b",
    r"\bvence\b",
    r"\bbolet(o|os)\b",
    r"\bfatura\b",
    r"\bcobran(ç|c)a\b",
    r"\bpagamento\b",
    r"\brenova(ç|c)ão\b",
    r"\bmensalidade\b",
    r"\bmatr[ií]cula\b",
    r"\bescola\b",
    r"\brematr[ií]cula\b",
    r"\bprova\b",
    r"\bmaterial\b",
    r"\brecibo\b",
    r"\bimposto\b",
    r"\birpf\b",
    r"\bseguro\b",
    r"\bassinatura\b",
    r"\bbanco\b",
    r"\bcart[aã]o\b",
    r"\bconta\b",
    r"\bpix\b",
]


TECH_ALERT_PATTERNS = [
    r"\brender\b",
    r"\brailway\b",
    r"\bdeployment\b",
    r"\bcrash\b",
    r"\bserver failure\b",
    r"\binstance failed\b",
    r"\berror\b",
    r"\bexception\b",
    r"\blog\b",
    r"\bstatuspage\b",
]


def _safe(x: Any) -> str:
    return (x or "").strip()


def _looks_like_tech_alert(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in TECH_ALERT_PATTERNS)


def _intent_score(subject: str, sender: str, snippet: str) -> int:
    hay = f"{subject}\n{sender}\n{snippet}".lower()
    score = 0

    # derruba alertas técnicos
    if _looks_like_tech_alert(hay):
        score -= 35

    for p in HIGH_INTENT_PATTERNS:
        if re.search(p, hay):
            score += 18

    if any(w in hay for w in ["urgente", "importante", "ação necessária", "prazo", "último dia"]):
        score += 12

    if any(w in hay for w in ["off", "promo", "desconto", "newsletter", "oferta", "sale"]):
        score -= 10

    score = max(0, min(100, score))
    return score


def _bucket(score: int) -> str:
    if score >= 75:
        return "ALTA"
    if score >= 45:
        return "MÉDIA"
    return "BAIXA"


def _human_summary(subject: str, snippet: str) -> str:
    hay = (subject + " " + snippet).lower()

    if re.search(r"\brenova", hay):
        return "Parece renovação/assinatura chegando perto do prazo — vale abrir pra não ter surpresa."
    if re.search(r"\bfatura|\bbolet|\bcobran|\bpagamento|\bvenc", hay):
        return "Cara de cobrança/fatura com prazo — eu abriria pra conferir valor e data de vencimento."
    if re.search(r"\bescola|\bmatr|\brematr|\bmensalidade|\bprova|\bmaterial", hay):
        return "Assunto de escola (mensalidade/rematrícula/aviso) — melhor checar."
    if re.search(r"\brecibo|\bimposto|\birpf", hay):
        return "Documento/recibo/impostos — pode ser algo pra guardar ou resolver."
    if _looks_like_tech_alert(hay):
        return "Alerta técnico de sistema/serviço (pouco relevante pra você)."

    snippet_clean = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet_clean) > 160:
        snippet_clean = snippet_clean[:160].rstrip() + "…"
    return f"Resumo: {snippet_clean}" if snippet_clean else "Não veio preview suficiente; vale abrir se o assunto te interessar."


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for e in emails:
        subject = _safe(e.get("subject")) or "(sem assunto)"
        sender = _safe(e.get("from")) or _safe(e.get("sender")) or "(remetente não identificado)"
        snippet = _safe(e.get("snippet")) or _safe(e.get("body_preview")) or ""

        score = _intent_score(subject, sender, snippet)
        bucket = _bucket(score)
        one_liner = _human_summary(subject, snippet)

        items.append(
            {
                "subject": subject,
                "from": sender,
                "snippet": snippet,
                "score": score,
                "bucket": bucket,
                "one_liner": one_liner,
            }
        )

    items.sort(key=lambda x: ({"ALTA": 0, "MÉDIA": 1, "BAIXA": 2}[x["bucket"]], -x["score"]))
    return items


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    groups = {"ALTA": [], "MÉDIA": [], "BAIXA": []}
    for it in items:
        groups[it["bucket"]].append(it)

    lines = []
    lines.append("📬 Resumo do inbox (foco: banco/contas, escola e prazos)\n")

    def add_group(title: str, arr: List[Dict[str, Any]]):
        if not arr:
            return
        lines.append(f"Emails com prioridade {title}\n")
        for idx, it in enumerate(arr, 1):
            lines.append(f"{idx}) [{it['score']}/100] {it['subject']}")
            lines.append(f"- De: {it['from']}")
            lines.append(f"- Em 1 linha: {it['one_liner']}\n")

    add_group("ALTA", groups["ALTA"])
    add_group("MÉDIA", groups["MÉDIA"])

    if groups["BAIXA"]:
        lines.append("Emails de BAIXA prioridade (se sobrar tempo)\n")
        for idx, it in enumerate(groups["BAIXA"], 1):
            lines.append(f"{idx}) [{it['score']}/100] {it['subject']}")
            lines.append(f"- Em 1 linha: {it['one_liner']}\n")

    return "\n".join(lines).strip()


# (opcional) Compatibilidade com versão antiga, se algum código ainda chamar build_summary
def build_summary(emails: List[Dict[str, Any]]) -> str:
    items = build_items(emails)
    return build_summary_from_items(items)
