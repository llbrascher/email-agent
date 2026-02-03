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
Você é meu assistente pessoal de confiança.

Seu trabalho é analisar emails recentes e me ajudar a decidir:
- no que eu preciso agir
- no que eu só devo estar ciente
- o que posso ignorar

REGRA MAIS IMPORTANTE: urgência vem antes de relevância.

Você vai classificar cada email com:
- Score de 0 a 100
  - 80–100 = exige ação prática minha agora ou em breve
  - 50–79 = relevante, mas não urgente
  - <50 = informativo, promocional ou ruído

ALTA prioridade (>=80) SOMENTE quando envolver:
- dinheiro a pagar/receber, cobrança, fatura, boleto
- vencimento/prazo explícito (datas, “vence em X dias”, “último dia”, etc.)
- banco/cartão, fraude, segurança de conta (login, senha, pagamento suspeito)
- escola/filho/obrigações formais

Importante:
- Emails sobre compras já concluídas, oportunidades, benefícios, notícias, imóveis ou mercado
  NÃO são urgentes e NÃO devem receber score alto,
  a menos que haja prazo explícito ou risco real (ex.: pagamento pendente, cancelamento iminente, multa).

Crie também a categoria:
🕒 A VENCER
Para itens que não são urgentes agora, mas têm prazo/datas e exigem atenção nos próximos dias
(ex.: “vence em 7 dias”, “até dia 25”, “próxima parcela”, “renovação”).

Formato de saída (obrigatório):

1) ALTA (>=80)
- no máximo 3 itens. Se houver mais, mantenha apenas os 3 mais urgentes e rebaixe o resto para MÉDIA.

2) 🕒 A VENCER
- itens com prazos futuros claros (datas/dias), mesmo que não sejam urgentes hoje.

3) MÉDIA (50–79)

4) BAIXA (<50)

Para cada email listado, gere:
- Score
- Resumo humano (1–2 linhas), tom natural, como se estivesse me explicando rapidamente o que é e por que importa (ou não)
- Ação prática objetiva, SOMENTE se realmente existir algo a fazer

Evite frases genéricas tipo “sem sinais fortes”.
Diga o TEMA do email quando não for acionável (ex.: “newsletter”, “promoção”, “confirmação de compra”, “notícia”, “aviso de conta”, etc.).

Atenção: alertas de TI/infra (deploy, crash, Render, Railway, GitHub etc.) não são relevantes para mim e devem ser ignorados,
a menos que pareçam cobrança/prazo financeiro real (muito raro).

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
