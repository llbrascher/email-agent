import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


PROMPT_TEMPLATE = (
    "Você é meu assistente pessoal de confiança.\n\n"
    "Seu trabalho é analisar emails recentes e me ajudar a decidir:\n"
    "- no que eu preciso agir\n"
    "- no que eu só devo estar ciente\n"
    "- o que posso ignorar\n\n"
    "REGRA MAIS IMPORTANTE: urgência vem antes de relevância.\n\n"
    "Classifique cada email com Score de 0 a 100:\n"
    "- 80–100 = exige ação prática minha agora ou em breve\n"
    "- 50–79 = relevante, mas não urgente\n"
    "- <50 = informativo, promocional ou ruído\n\n"
    "ALTA prioridade (>=80) SOMENTE quando envolver:\n"
    "- dinheiro a pagar ou receber, cobrança, fatura, boleto\n"
    "- vencimento ou prazo explícito\n"
    "- banco/cartão, fraude, segurança de conta\n"
    "- escola, filho, obrigações formais\n\n"
    "Crie também a categoria:\n"
    "🕒 A VENCER\n"
    "Para emails com prazo futuro, mas sem urgência imediata.\n\n"
    "Ignore completamente alertas técnicos de TI/infra "
    "(Render, Railway, GitHub, deploy, crash, server failure).\n\n"
    "Formato de saída OBRIGATÓRIO:\n\n"
    "ALTA (>=80)\n"
    "🕒 A VENCER\n"
    "MÉDIA (50–79)\n"
    "BAIXA (<50)\n\n"
    "Para cada email:\n"
    "- Score\n"
    "- Resumo humano (1–2 linhas, linguagem natural)\n"
    "- Ação prática SOMENTE se houver algo real a fazer\n\n"
    "Explique o TEMA do email quando não for acionável.\n\n"
    "Emails para analisar:\n\n"
    "{emails}"
)


def build_items(emails):
    items = []
    for e in emails:
        items.append({
            "subject": e.get("subject", ""),
            "from": e.get("from", ""),
            "snippet": e.get("snippet", "")
        })
    return items


def build_summary_from_items(items):
    if not items:
        return ""

    emails_text = "\n".join(
        f"- Assunto: {i['subject']} | De: {i['from']} | Trecho: {i['snippet']}"
        for i in items
    )

    prompt = PROMPT_TEMPLATE.format(emails=emails_text)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Você é um assistente pessoal experiente e confiável."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=1200
    )

    return response.choices[0].message.content.strip()
