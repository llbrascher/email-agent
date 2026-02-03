import os
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple

# OpenAI SDK (openai>=1.x)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# ---------------------------
# Helpers de normalização
# ---------------------------
def _get_subject(e: Dict[str, Any]) -> str:
    return (e.get("subject") or e.get("Subject") or "").strip()


def _get_from(e: Dict[str, Any]) -> str:
    return (e.get("from") or e.get("From") or e.get("sender") or "").strip()


def _get_snippet(e: Dict[str, Any]) -> str:
    return (e.get("snippet") or e.get("Snippet") or e.get("body_preview") or "").strip()


def _get_date(e: Dict[str, Any]) -> str:
    # tenta vários campos comuns
    for k in ("date", "Date", "internalDate", "received_at", "receivedAt"):
        v = e.get(k)
        if v:
            return str(v)
    return ""


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converte a lista de emails em itens mínimos para classificação/resumo."""
    items = []
    for e in emails or []:
        subj = _get_subject(e)
        frm = _get_from(e)
        snip = _get_snippet(e)
        if not subj and not snip:
            continue
        items.append(
            {
                "subject": subj,
                "from": frm,
                "snippet": snip[:800],  # corta pra não explodir o prompt
                "date": _get_date(e),
            }
        )
    return items


# ---------------------------
# Prompt principal
# ---------------------------
def _build_prompt(items: List[Dict[str, Any]]) -> str:
    return f"""
Você é o assistente pessoal do Leandro. Sua tarefa é ler uma lista de emails (apenas assunto, remetente e snippet)
e devolver uma triagem em 3 níveis com SCORE (0–100), um resumo útil e uma ação prática.

Objetivo do Leandro:
- O que MAIS importa: banco/contas/pagamentos/boletos, escola (filho), assuntos com prazo/vencimento/renovação,
  cobranças, faturas, impostos, multas, documentos, reservas/viagens com pagamento, compras com entrega relevante.
- O que NÃO importa (jogue para BAIXA, score baixo): alertas de infra/devops (Render, Railway, server down, deploy crashed),
  newsletters genéricas, promoções, marketing, esportes, redes sociais, releases e “FYI”.

Regras de pontuação (importante):
- 90–100: exige ação real e em breve (vencimento, cobrança, risco de perder serviço, pagamento pendente, escola com prazo, banco pedindo algo).
- 80–89: importante, mas pode ser resolvido em 1–3 dias (entrega/compra, confirmação de dados de pagamento, alteração de conta).
- 50–79: relevante, mas sem urgência clara (informativo profissional útil, aviso que pode virar pendência).
- 0–49: ruído (promo/newsletter/infra alert).

Estilo do texto:
- Não escreva como robô.
- Fale como um assistente humano: direto, útil, com 1–2 frases que realmente expliquem do que se trata.
- Evite frases vazias tipo “sem sinais fortes de banco...”. Sempre diga o TEMA do email.

Saída:
- Devolva JSON (apenas JSON) com a chave "results": uma lista de objetos, um por email.
- Cada objeto deve ter:
  - "score": número inteiro 0–100
  - "summary": 1–2 frases (o que é e por que importa)
  - "action": 1 frase com ação sugerida (prática)
  - "bucket": "ALTA" (>=80) | "MEDIA" (50-79) | "BAIXA" (<50)

Emails:
{json.dumps(items, ensure_ascii=False, indent=2)}
""".strip()


def _call_openai(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("Biblioteca openai não encontrada. Verifique requirements.txt (openai>=1.0.0).")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não definido nas variáveis de ambiente.")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    prompt = _build_prompt(items)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Você classifica emails e sugere ações com precisão."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    content = (resp.choices[0].message.content or "").strip()
    # tenta parsear JSON “na unha”
    data = json.loads(content)
    results = data.get("results", [])
    if not isinstance(results, list):
        return []
    return results


def _format_telegram(results: List[Dict[str, Any]]) -> str:
    high = [r for r in results if r.get("bucket") == "ALTA"]
    mid = [r for r in results if r.get("bucket") == "MEDIA"]
    low = [r for r in results if r.get("bucket") == "BAIXA"]

    def fmt_group(title: str, group: List[Dict[str, Any]]) -> str:
        if not group:
            return ""
        lines = [f"*{title}*"]
        for i, r in enumerate(group, 1):
            score = int(r.get("score", 0))
            summary = (r.get("summary") or "").strip()
            action = (r.get("action") or "").strip()
            lines.append(f"\n{i}) *Score:* {score}\n*Resumo:* {summary}\n*Ação:* {action}")
        return "\n".join(lines)

    parts = []
    parts.append(fmt_group("ALTA (>=80)", high))
    parts.append(fmt_group("MÉDIA (50–79)", mid))
    parts.append(fmt_group("BAIXA (<50)", low))

    msg = "\n\n".join([p for p in parts if p.strip()])

    # fallback
    if not msg.strip():
        msg = "Nada relevante agora. Se quiser, eu posso revisar de novo mais tarde."

    return msg


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    """Novo fluxo: recebe items e devolve texto pronto para Telegram."""
    if not items:
        return ""

    results = _call_openai(items)

    # normaliza bucket por segurança
    for r in results:
        s = int(r.get("score", 0))
        if s >= 80:
            r["bucket"] = "ALTA"
        elif s >= 50:
            r["bucket"] = "MEDIA"
        else:
            r["bucket"] = "BAIXA"

    return _format_telegram(results)


# Compatibilidade com versões antigas do main.py
def build_summary(emails: List[Dict[str, Any]]) -> str:
    items = build_items(emails)
    return build_summary_from_items(items)
