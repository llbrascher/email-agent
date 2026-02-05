# summarizer.py
import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI


# =========================
# Config
# =========================
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_ITEMS = int(os.getenv("SUMMARY_MAX_ITEMS", "30"))
REQUEST_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "30"))
RETRIES = int(os.getenv("OPENAI_RETRIES", "2"))  # 2 tentativas no total (0 e 1)
SLEEP_BETWEEN_RETRIES_S = float(os.getenv("OPENAI_RETRY_SLEEP_S", "2"))


client = OpenAI()


# =========================
# Helpers
# =========================
def _safe_get(d: Dict[str, Any], key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default


def _email_to_item(e: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte o email (dict vindo do gmail_client.py) para um item consistente.
    Ajuste os nomes se seu gmail_client usa chaves diferentes.
    """
    subject = _safe_get(e, "subject", "") or _safe_get(e, "Subject", "") or ""
    frm = _safe_get(e, "from", "") or _safe_get(e, "From", "") or ""
    snippet = _safe_get(e, "snippet", "") or _safe_get(e, "body", "") or ""

    # data pode vir em iso, timestamp, etc — aqui mantemos como string simples
    date = _safe_get(e, "date", "") or _safe_get(e, "internalDate", "") or ""

    return {
        "subject": str(subject).strip(),
        "from": str(frm).strip(),
        "date": str(date).strip(),
        "snippet": str(snippet).strip(),
    }


def build_items(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Função esperada pelo main.py.
    """
    items = []
    for e in (emails or [])[:MAX_ITEMS]:
        items.append(_email_to_item(e))
    return items


def _build_prompt(items: List[Dict[str, Any]]) -> str:
    """
    Prompt: humanizado + foco em banco/contas/escola/prazos.
    """
    lines = []
    for i, it in enumerate(items, start=1):
        lines.append(
            f"{i}) FROM: {it.get('from','')}\n"
            f"   SUBJECT: {it.get('subject','')}\n"
            f"   SNIPPET: {it.get('snippet','')}\n"
        )

    emails_block = "\n".join(lines)

    return f"""
Você é meu assistente pessoal. Sua missão é me ajudar a NÃO perder prazos e assuntos críticos.

**O que é mais importante para mim (priorize isso):**
- banco, cartão, cobrança, fatura, parcelas, boletos, pagamentos, fraudes, segurança, imposto
- contas a vencer (prazo, vencimento, renovação), serviços (internet, telefone, energia, condomínio)
- escola (mensalidade, reunião, agenda, recados, documentos, matrícula)
- coisas com data limite / action required / confirmação necessária

**O que NÃO quero como prioridade (normalmente BAIXA):**
- alertas técnicos de sistemas (Render, Railway, GitHub Actions etc.)
- newsletters, promoções, marketing genérico (a menos que seja cobrança/prazo real)

Quero que você produza um resumo em 3 blocos: ALTA, MÉDIA e BAIXA.
- Dê um score de 0 a 100.
- Fale num tom humano, como um assistente (nada de "sem sinais fortes de...").
- Para cada email: diga o tema em 1 linha e uma ação prática curta (se houver).

Responda em JSON **válido**, neste formato:

{{
  "alta": [{{"score": 0, "titulo": "", "resumo": "", "acao": ""}}],
  "media": [{{"score": 0, "titulo": "", "resumo": "", "acao": ""}}],
  "baixa": [{{"score": 0, "titulo": "", "resumo": "", "acao": ""}}]
}}

Aqui estão os emails (mais recentes primeiro):

{emails_block}
""".strip()


def _call_openai_for_json(prompt: str) -> Dict[str, Any]:
    """
    Chama OpenAI pedindo JSON; se vier algo inválido, lança exceção com o raw anexado.
    """
    last_err = None
    for attempt in range(RETRIES):
        try:
            resp = client.responses.create(
                model=MODEL,
                input=prompt,
                # pedimos "text" e parseamos nós mesmos (mais compatível)
                # se preferir, podemos evoluir depois para response_format json_schema
                timeout=REQUEST_TIMEOUT_S,
            )

            # Extrai texto de forma robusta (SDK novo pode variar)
            text = ""
            try:
                text = resp.output_text or ""
            except Exception:
                text = ""

            raw = (text or "").strip()

            if not raw:
                raise ValueError("OpenAI returned empty text (cannot parse JSON)")

            # às vezes vem cercado por ```json ... ```
            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw.replace("json", "", 1).strip()

            # tenta JSON
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("JSON parsed but is not an object")
                return data
            except json.JSONDecodeError as je:
                # Anexa começo do texto pro log
                preview = raw[:240].replace("\n", "\\n")
                raise ValueError(f"JSON decode failed. Preview: {preview}") from je

        except Exception as e:
            last_err = e
            if attempt < RETRIES - 1:
                time.sleep(SLEEP_BETWEEN_RETRIES_S)
                continue
            raise last_err


def _format_message(data: Dict[str, Any]) -> str:
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

    alta = data.get("alta") or []
    media = data.get("media") or []
    baixa = data.get("baixa") or []

    msg = ""
    msg += _fmt_block("📌 Emails com prioridade ALTA", alta)
    msg += "\n" + _fmt_block("🟡 Emails com prioridade MÉDIA", media)
    msg += "\n" + _fmt_block("⚪ Emails com prioridade BAIXA (ação opcional)", baixa)
    return msg.strip()


def build_summary_from_items(items: List[Dict[str, Any]]) -> str:
    """
    Função esperada pelo main.py.
    Retorna mensagem pronta para Telegram.
    """
    prompt = _build_prompt(items)

    data = _call_openai_for_json(prompt)
    return _format_message(data)


# (compatibilidade com versões antigas, se seu main cair aqui)
def build_summary(emails: List[Dict[str, Any]]) -> str:
    items = build_items(emails)
    if not items:
        return ""
    return build_summary_from_items(items)
