import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_items(emails):
    """
    Normaliza emails vindos do Gmail para um formato compacto
    """
    items = []
    for e in emails:
        items.append({
            "subject": e.get("subject", ""),
            "from": e.get("from", ""),
            "snippet": e.get("snippet", "")
        })
    return items


def build_summary_from_items(items):
    """
    Usa o ChatGPT para classificar, resumir e priorizar emails
    com foco em vida prática (banco, contas, escola, prazos).
    """

    if not items:
        return ""

    compact = "\n".join(
        f"- Assunto: {i['subject']} | De: {i['from']} | Trecho: {i['snippet']}"
        for i in items
    )

    prompt = f"""
Você é meu assistente pessoal de confiança.

Seu trabalho é analisar emails recentes e me ajudar a decidir:
- no que eu preciso agir
- no que eu só devo estar ciente
- o que posso ignorar

REGRA MAIS IMPORTANTE: urgência vem antes de relevância.

Classifique cada email com Score de 0 a 100:
- 80–100 = exige ação prática minha agora ou em breve
- 50–79 = relevante, mas não urgente
- <50 = informativo, promocional ou ruído

ALTA prioridade (>=80) SOMENTE quando envolver:
- dinheiro a pagar ou receber, cobrança, fatura, boleto
- vencimento ou prazo explícito (datas, “vence em X dias”, “último dia”)
- banco/cartão, fraude, segurança de conta
- escola, filho, obrigações formais

Emails sobre:
- compras já concluídas
- oportunidades
- benefícios
- imóveis
- notícias ou macroeconomia

NÃO são urgentes e NÃO devem receber score alto,
a menos que exista prazo claro ou risco financeiro real.

Crie também a categoria:
🕒 A VENCER
Para emails que mencionam prazos futuros (datas/dias),
mas que ainda não exigem ação imediata.

Ignore alertas técnicos de TI/infra
(Render, Railway, GitHub, deploy, crash, server failure, etc.),
pois não são relevantes para mim.

Formato de saída OBRIGATÓRIO:

ALTA (>=80) — no máximo 3 itens  
🕒 A VENCER  
MÉDIA (50–79)  
BAIXA (<50)

Para cada email listado, gere:
- Score
- Resumo humano (1–2 linhas), em tom natural,
  como se estivesse me explicando rapidamente o que é o email
  e por que ele importa (ou não).
- Ação prática objetiva, SOMENTE se houver algo real a fazer.

Evite frases genéricas como “sem sinais fortes”.
Explique o TEMA do email quando não for acionável
(ex.: “confirmação de compra”, “promoção”, “newsletter”, “aviso de conta”).

Emails para analisar:
{compact}
""".strip()

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
