# summarizer.py
import json
import os
import time
from typing import Any, Dict, List

from openai import OpenAI


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_ITEMS = int(os.getenv("SUMMARY_MAX_ITEMS", "30"))

# Novos controles de “poluição” na BAIXA
LOW_MAX_ITEMS = int(os.getenv("LOW_MAX_ITEMS", "5"))  # quantos itens BAIXA listar no máximo
LOW_SHOW_ONLY_USEFUL = os.getenv("LOW_SHOW_ONLY_USEFUL", "1") == "1"  # se 1, BAIXA só mostra “úteis”
LOW_GROUP_REST = os.getenv("LOW_GROUP_REST", "1") == "1"  # se 1, agrupa o resto em uma linha

REQUEST_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "30"))
RETRIES = int(os.getenv("OPENAI_RETRIES", "2"))
SLEEP_BETWEEN_RETRIES_S = float(os.getenv("OPENAI_RETRY_SLEEP_S", "2"))

client = OpenAI()


def _safe_get(d: Dict[str, Any], key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default


def _email_to_item(e: Dict[str, Any]) -> Dict[str, Any]:
    subject = _safe_get(e, "subject", "") or _safe_get(e, "Subject", "") or ""
    frm = _safe_get(e, "from", "") or _safe_get(e, "From", "") or ""
    snippet = _safe_get(e, "snippet", "") or _safe_get(e, "body", "") or ""
    date = _safe_get(e, "date", "") or _safe_get(e, "internalDate", "") or ""

    return {
        "subject": str(subject).strip(),
        "from": str(frm).strip(),
        "date": str(date).strip(),
        "snippet": str(snippet).strip(),
    }


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for e in (emails or [])[:MAX_ITEMS]:
        items.append(_email_to_item(e))
    return items


def _build_prompt(items: List[Dict[str, Any]]) -> str:
    lines = []
    for i, it in enumerate(items, start=1):
        lines.append(
            f"{i}) FROM: {it.get('from','')}\n"
            f"   SUBJECT: {it.get('subject','')}\n"
            f"   SNIPPET: {it.get('snippet','')}\n"
        )
    emails_block = "\n".join(lines)

    return f"""
Você é meu assistente pessoal. Seu trabalho é me ajudar a NÃO perder prazos e a focar no que importa.

### Prioridade máxima (suba score e coloque em ALTA quando aparecer)
- Banco/contas: boleto, fatura, parcela, cobrança, pagamento, vencimento, débito, Pix, cartão, juros, multa, protesto, Serasa, imposto.
- Moradia: aluguel, condomínio, IPTU, energia, água, internet, telefone.
- Escola: mensalidade, reunião, recados, agenda, documentos, matrícula.
- Qualquer coisa com data limite (“vence hoje/amanhã”, “último dia”, “prazo”, “renovação”, “action required”).

### Regras fortes (importante)
1) Alertas técnicos e TI DEVEM SER BAIXA por padrão:
   - Render, Railway, GitHub, deploy, crash, logs, uptime, API key, billing setup de API/Cloud (Gemini/OpenAI/AWS/GCP), incident, monitoring, SRE, CI/CD.
   - Só suba para MÉDIA/ALTA se houver risco direto financeiro pessoal (ex.: cobrança real, fatura vencendo, pagamento pendente no cartão).
2) Newsletters, promoções e convites sociais tendem a BAIXA.

### Regras para reduzir poluição (BAIXA)
- Evite listar dezenas de itens irrelevantes.
- Use o campo "util" para marcar BAIXA que ainda vale a pena mostrar (ex.: confirmação de pagamento, comprovante, recibo, rastreio/entrega, confirmação de reserva).
- Promoções/newsletters/convites sociais/alertas técnicos normalmente NÃO são "util".

### Tom
Quero um tom humano. Nada de “sem sinais fortes de…”.
Diga o tema em 1 linha com um porquê curto.
Ação prática objetiva.

### Saída obrigatória
Responda em JSON válido, exatamente neste formato:

{{
  "alta": [{{"score": 0, "titulo": "", "resumo": "", "acao": ""}}],
  "media": [{{"score": 0, "titulo": "", "resumo": "", "acao": ""}}],
  "baixa": [{{"score": 0, "titulo": "", "resumo": "", "acao": "", "util": false}}]
}}

### Critério de score (guia rápido)
- 90–100: prazo muito curto / cobrança / pagamento / risco claro.
- 80–89: importante mas não “agora-agora”.
- 50–79: relevante, mas sem urgência evidente.
- 0–49: dispensável / promo / newsletter / social / TI.

Aqui estão os emails (mais recentes primeiro):

{emails_block}
""".strip()


def _call_openai_for_json(prompt: str) -> Dict[str, Any]:
    last_err = None

    for attempt in range(RETRIES):
        try:
            resp = client.responses.create(
                model=MODEL,
                input=prompt,
                timeout=REQUEST_TIMEOUT_S,
            )

            text = ""
            try:
                text = resp.output_text or ""
            except Exception:
                text = ""

            raw = (text or "").strip()
            if not raw:
                raise ValueError("OpenAI returned empty text (cannot parse JSON)")

            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw.replace("json", "", 1).strip()

            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON parsed but is not an object")
            return data

        except Exception as e:
            last_err = e
            if attempt < RETRIES - 1:
                time.sleep(SLEEP_BETWEEN_RETRIES_S)
                continue
            raise last_err


def _normalize_list(x) -> List[Dict[str, Any]]:
    if not x:
        return []
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    return []


def _trim_low(low: List[Dict[str, Any]]) -> (List[Dict[str, Any]], int):
    """
    - Se LOW_SHOW_ONLY_USEFUL: mantém apenas baixa com util=True
    - Limita em LOW_MAX_ITEMS
    - Retorna (lista_final, qtd_agrupada)
    """
    original_count = len(low)

    if LOW_SHOW_ONLY_USEFUL:
        low = [it for it in low if bool(it.get("util"))]

    low = low[: max(0, LOW_MAX_ITEMS)]
    grouped = max(0, original_count - len(low))
    return low, grouped


def _format_message(data: Dict[str, Any]) -> str:
    alta = _normalize_list(data.get("alta"))
    media = _normalize_list(data.get("media"))
    baixa = _normalize_list(data.get("baixa"))

    baixa_final, baixa_grouped = _trim_low(baixa)

    def _fmt_block(title: str, arr: List[Dict[str, Any]]) -> str:
        if not arr:
            return f"{title}\n\n(sem itens)\n"
        out = [title, ""]
        for idx, it in enumerate(arr, start=1):
            score = it.get("score", "")
            titulo = (it.get("titulo") or "").strip()
            resumo = (it.get("resumo") or "").strip()
            acao = (it.get("acao") or "").strip()

            out.append(f"{idx}) [{score}/100] {titulo}".strip())
            if resumo:
                out.append(f"   • {resumo}")
            if acao:
                out.append(f"   • Ação: {acao}")
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    msg = ""
    msg += _fmt_block("📌 Emails com prioridade ALTA", alta)
    msg += "\n" + _fmt_block("🟡 Emails com prioridade MÉDIA", media)

    # BAIXA: só mostra a lista (já filtrada) e opcionalmente um “rodapé” agrupado
    baixa_title = "⚪ Emails com prioridade BAIXA (ação opcional)"
    msg += "\n" + _fmt_block(baixa_title, baixa_final)

    if LOW_GROUP_REST and baixa_grouped > 0:
        msg += f"\n(🧹 Mais {baixa_grouped} emails irrelevantes/promoções foram ignorados pra não poluir.)\n"

    return msg.strip()


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    prompt = _build_prompt(items)
    data = _call_openai_for_json(prompt)
    return _format_message(data)


def build_summary(emails: List[Dict[str, Any]]) -> str:
    items = build_items(emails)
    if not items:
        return ""
    return build_summary_from_items(items)
