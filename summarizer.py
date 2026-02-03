import os
import re
from typing import Any, Dict, List

from openai import OpenAI

client = OpenAI()


# Palavras/assuntos que você quer priorizar
HIGH_INTENT_KEYWORDS = [
    "boleto", "fatura", "venc", "vencimento", "atras", "cobran", "pagamento",
    "cartão", "cartao", "limite", "juros", "multa", "débito", "debito",
    "conta", "banco", "pix", "transfer", "itau", "bradesco", "santander", "nubank",
    "caixa", "bb", "banco do brasil", "inter", "c6", "sicredi",
    "mensalidade", "escola", "colégio", "colegio", "matrícula", "matricula",
    "renovação", "renovacao", "prazo", "assinatura", "renovar", "vence em",
    "a vencer", "último aviso", "ultima chamada", "notificação", "notificacao",
]


# Alertas que NÃO te interessam (infra/dev)
# Se bater nisso, a gente joga fora (ou deixa como muito baixo)
INFRA_NOISE_PATTERNS = [
    r"\brender\b",
    r"\brailway\b",
    r"\bdeploy\b",
    r"\bdeployment\b",
    r"\bcrash\b",
    r"\bfailed\b",
    r"\bserver failure\b",
    r"\bincident\b",
    r"\bon[- ]call\b",
    r"\bgithub\b",
    r"\bactions\b",
    r"\bstatus\b",
    r"\bmonitor\b",
    r"\blog\b",
    r"\berror\b",
    r"\bexception\b",
]


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _is_infra_noise(subject: str, sender: str) -> bool:
    text = f"{subject} {sender}".lower()
    for pat in INFRA_NOISE_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _looks_important(subject: str, snippet: str, sender: str) -> bool:
    text = f"{subject} {snippet} {sender}".lower()
    return any(k in text for k in HIGH_INTENT_KEYWORDS)


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normaliza emails e remove ruído de infra.
    Espera que cada email tenha campos tipo: subject/from/snippet/date.
    """
    items: List[Dict[str, Any]] = []

    for e in emails or []:
        subject = _safe_str(e.get("subject") or e.get("Subject"))
        sender = _safe_str(e.get("from") or e.get("From") or e.get("sender"))
        snippet = _safe_str(e.get("snippet") or e.get("Snippet") or e.get("body") or "")

        # 1) Mata alertas de infra (Railway/Render etc)
        # (a não ser que pareça cobrança/prazo etc, o que é raro)
        if _is_infra_noise(subject, sender) and not _looks_important(subject, snippet, sender):
            continue

        item = {
            "subject": subject,
            "from": sender,
            "snippet": snippet[:500],  # limita pra não estourar token
            "raw": e,
        }

        # score simples local (antes do LLM)
        item["priority_hint"] = 90 if _looks_important(subject, snippet, sender) else 40

        items.append(item)

    return items


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    """
    Usa ChatGPT para classificar e resumir de forma humana,
    focando em banco/contas/escola/prazos, e dando ações concretas.
    """
    if not items:
        return ""

    # Monta um payload compacto pro modelo
    compact = []
    for it in items:
        compact.append({
            "subject": it["subject"],
            "from": it["from"],
            "snippet": it["snippet"],
            "priority_hint": it.get("priority_hint", 40),
        })

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # pode trocar no env
    max_items = int(os.getenv("MAX_ITEMS_IN_SUMMARY", "25"))
    compact = compact[:max_items]

    prompt = f"""
Você é um assistente pessoal humano e direto, escrevendo em português do Brasil.
Seu dono NÃO quer alertas de TI/infra (deploy, crash, render, railway, github etc). Esses devem ficar fora.

Objetivo: destacar o que realmente importa para vida prática:
- banco, contas, cobranças, faturas, boletos, vencimentos, multas, juros
- escola/colégio/mensalidades/matrícula
- coisas com prazo (renovação, assinatura, "vence em X dias")
- qualquer risco financeiro ou algo que exige ação

Para cada e-mail, gere:
- score [0-100] (impacto/urgência real)
- um resumo humano de 1–2 linhas sobre "do que se trata"
- uma ação prática objetiva (se houver)
- agrupar em: ALTA (>=80), MÉDIA (50-79), BAIXA (<50)

Não use frases vazias tipo "sem sinais fortes...".
Fale o tema (ex.: "promoção", "compra confirmada", "newsletter", "pesquisa profissional", "notificação social", etc).

Aqui estão os emails (subject/from/snippet):
{compact}
""".strip()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Você resume emails com tom humano e foco em ações práticas."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return resp.choices[0].message.content.strip()
