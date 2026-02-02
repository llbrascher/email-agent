import re
from datetime import datetime
from typing import List, Dict, Any


# Palavras/assuntos que você quer priorizar
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
    r"\bnota fiscal\b",
    r"\brecibo\b",
    r"\bimposto\b",
    r"\birpf\b",
    r"\bseguro\b",
    r"\bassinatura\b",
    r"\brenova\b",
    r"\bsuspens(a|ão)\b",
    r"\bbanco\b",
    r"\bcart[aã]o\b",
    r"\bconta\b",
    r"\bpix\b",
    r"\btransfer[eê]ncia\b",
]

# Remover ruído de alertas técnicos (devops / serviços)
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


def _safe(s: Any) -> str:
    return (s or "").strip()


def _looks_like_tech_alert(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in TECH_ALERT_PATTERNS)


def _intent_score(subject: str, sender: str, snippet: str) -> int:
    hay = f"{subject}\n{sender}\n{snippet}".lower()

    score = 0

    # Penaliza alertas técnicos
    if _looks_like_tech_alert(hay):
        score -= 35

    # Dá peso alto para “assuntos da vida real”
    for p in HIGH_INTENT_PATTERNS:
        if re.search(p, hay):
            score += 18

    # Heurísticas extras
    if any(w in hay for w in ["urgente", "importante", "ação necessária", "prazo", "último dia", "final call"]):
        score += 12

    # Promoções/newsletters: costuma ser baixo
    if any(w in hay for w in ["off", "promo", "desconto", "newsletter", "oferta", "sale", "black friday"]):
        score -= 10

    # Clamps
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score


def _bucket(score: int) -> str:
    if score >= 75:
        return "ALTA"
    if score >= 45:
        return "MÉDIA"
    return "BAIXA"


def _human_summary(subject: str, sender: str, snippet: str) -> str:
    """
    Resumo “com cara de assistente”:
    - 1 linha que diga o que é e por que importa
    """
    s = subject
    sn = snippet

    # tenta extrair “o que parece ser”
    if re.search(r"\brenova", (s + " " + sn).lower()):
        return "Parece uma renovação/assinatura chegando no prazo — vale abrir pra ver condições e evitar interrupção."
    if re.search(r"\bfatura|\bbolet|\bcobran|\bpagamento|\bvenc", (s + " " + sn).lower()):
        return "Isso tem cara de cobrança/fatura com prazo — eu abriria pra checar valor e data de vencimento."
    if re.search(r"\bescola|\bmatr|\brematr|\bmensalidade|\bprova|\bmaterial", (s + " " + sn).lower()):
        return "Assunto de escola: provavelmente mensalidade, rematrícula ou aviso importante — melhor conferir."
    if re.search(r"\brecibo|\bnota fiscal|\bimposto|\birpf", (s + " " + sn).lower()):
        return "Parece documento/recibo/impostos — pode ser útil guardar ou já resolver pendência."
    if _looks_like_tech_alert(s + " " + sn):
        return "Alerta técnico de sistema/serviço. Se não for algo que você queira acompanhar, dá pra tratar como baixa prioridade."

    # fallback: usa assunto + pedaço do snippet de forma natural
    snippet_clean = re.sub(r"\s+", " ", sn).strip()
    if len(snippet_clean) > 140:
        snippet_clean = snippet_clean[:140].rstrip() + "…"

    if snippet_clean:
        return f"Resumo rápido: {snippet_clean}"
    return "Não veio muito conteúdo no preview, mas o assunto parece simples — vale abrir se tiver curiosidade."


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Entrada: lista de emails (dict) — esperamos pelo menos subject/from/snippet.
    Saída: lista de itens com score/bucket/resumo.
    """
    items = []
    for e in emails:
        subject = _safe(e.get("subject"))
        sender = _safe(e.get("from")) or _safe(e.get("sender"))
        snippet = _safe(e.get("snippet")) or _safe(e.get("body_preview")) or ""

        # se o Gmail não trouxe snippet, não quebra
        score = _intent_score(subject, sender, snippet)
        bucket = _bucket(score)
        one_liner = _human_summary(subject, sender, snippet)

        items.append(
            {
                "subject": subject or "(sem assunto)",
                "from": sender or "(remetente não identificado)",
                "snippet": snippet,
                "score": score,
                "bucket": bucket,
                "one_liner": one_liner,
            }
        )

    # Ordena: prioridade + score + assunto
    items.sort(key=lambda x: ({"ALTA": 0, "MÉDIA": 1, "BAIXA": 2}[x["bucket"]], -x["score"], x["subject"]))
    return items


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    """
    Formata a mensagem final para Telegram.
    """
    groups = {"ALTA": [], "MÉDIA": [], "BAIXA": []}
    for it in items:
        groups[it["bucket"]].append(it)

    lines = []
    lines.append("📬 **Resumo do seu inbox (com foco no que dá dor de cabeça se atrasar)**\n")

    def add_group(title: str, arr: List[Dict[str, Any]]):
        if not arr:
            return
        lines.append(f"**Emails com prioridade {title}**\n")
        for idx, it in enumerate(arr, 1):
            lines.append(f"{idx}) [{it['score']}/100] {it['subject']}")
            lines.append(f"- De: {it['from']}")
            lines.append(f"- Em 1 linha: {it['one_liner']}\n")

    add_group("ALTA", groups["ALTA"])
    add_group("MÉDIA", groups["MÉDIA"])

    # Para BAIXA: mantém, mas com texto útil (não “sem sinais fortes…”)
    if groups["BAIXA"]:
        lines.append("**Emails de BAIXA prioridade (se sobrar tempo)**\n")
        for idx, it in enumerate(groups["BAIXA"], 1):
            lines.append(f"{idx}) [{it['score']}/100] {it['subject']}")
            lines.append(f"- Em 1 linha: {it['one_liner']}\n")

    return "\n".join(lines).strip()
