# summarizer.py
# Objetivo: priorizar emails realmente úteis (banco/contas/escola/vencimentos) e
# rebaixar/ignorar alertas de sistemas (Render/Railway/etc).
#
# Espera receber `emails` como lista de dicts (ex.: vindos do gmail_client.py),
# contendo ao menos: subject, from (ou sender), snippet (opcional), date (opcional)
#
# Saída: string pronta para enviar ao Telegram.

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional


# -----------------------------
# Config
# -----------------------------

# Palavras/expressões que tipicamente NÃO interessam (infra/alertas, newsletters, promo)
IGNORE_SUBJECT_PATTERNS = [
    r"\bRender\b",
    r"\bRailway\b",
    r"\bDeployment crashed\b",
    r"\bServer failure\b",
    r"\bincident\b",
    r"\balert\b",
    r"\bstatus\b",
    r"\bmonitor\b",
    r"\bunhealthy\b",
    r"\bdown\b",
    r"\bcrash\b",
    r"\berror\b",
    r"\bfailure\b",
    r"\bSEV\b",
    r"\bPagerDuty\b",
    r"\bDatadog\b",
    r"\bSentry\b",
    r"\bUptime\b",
    r"\bNew Relic\b",
    r"\bAWS\b",
    r"\bGCP\b",
    r"\bAzure\b",
]

LOW_PRIORITY_PATTERNS = [
    r"\bnewsletter\b",
    r"\bpromo\b",
    r"\bdesconto\b",
    r"\boferta\b",
    r"\bmarketing\b",
    r"\búltimas horas\b",
    r"\bfinal call\b",
    r"\bTikTok\b",
    r"\bStrava\b",
    r"\bVans\b",
    r"\bEsporte\b",
]

# O que você quer como "mais importante"
HIGH_PRIORITY_KEYWORDS = [
    # Banco / financeiro
    "banco", "itau", "itaú", "bradesco", "santander", "nubank", "caixa", "bb", "banco do brasil",
    "fatura", "cartão", "cartao", "boleto", "pix", "transferência", "transferencia", "pagamento",
    "cobrança", "cobranca", "inadimplência", "inadimplencia", "juros", "multa",
    "limite", "fraude", "suspeita", "compra não reconhecida", "compra nao reconhecida",
    "comprovante", "extrato", "débito", "debito", "crédito", "credito",
    "renegociação", "renegociacao",
    # Contas a vencer
    "vencimento", "vence", "a vencer", "atraso", "em atraso", "segunda via", "2ª via", "2a via",
    "corte", "suspensão", "suspensao", "negativação", "negativacao",
    "iptu", "ipva", "condomínio", "condominio", "aluguel", "energia", "luz", "água", "agua",
    "internet", "telefone", "plano de saúde", "plano de saude",
    # Escola / filhos
    "escola", "colégio", "colegio", "mensalidade", "rematrícula", "rematricula",
    "boletim", "prova", "reunião", "reuniao", "coordenação", "coordenacao",
    "matrícula", "matricula", "material escolar", "sala", "turma",
    "agenda", "aviso", "comunicado",
]

MEDIUM_PRIORITY_KEYWORDS = [
    "google alerts", "alerta do google", "jtekt", "notícia", "noticia",
    "confirmação", "confirmacao", "reserva", "viagem", "documento",
]

# Data/“vencimento” costuma aparecer assim:
DATE_REGEXES = [
    r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",     # 05/02 ou 05/02/2026
    r"\b(\d{1,2})-(\d{1,2})(?:-(\d{2,4}))?\b",     # 05-02 ou 05-02-2026
    r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b",   # 05.02 ou 05.02.2026
]

DUE_HINTS = [
    "venc", "vence", "a vencer", "vencimento", "prazo", "deadline",
    "último dia", "ultimo dia", "final", "hoje", "amanhã", "amanha",
]


# -----------------------------
# Helpers
# -----------------------------

def _get(email: Dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        v = email.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _matches_any(text: str, patterns: List[str]) -> bool:
    t = text or ""
    for p in patterns:
        if re.search(p, t, flags=re.IGNORECASE):
            return True
    return False

def _contains_any(text: str, keywords: List[str]) -> bool:
    t = _norm(text)
    for kw in keywords:
        if kw in t:
            return True
    return False

def _extract_first_date(text: str) -> Optional[datetime]:
    if not text:
        return None

    now = datetime.now()
    for rx in DATE_REGEXES:
        m = re.search(rx, text)
        if not m:
            continue
        day = int(m.group(1))
        month = int(m.group(2))
        year_str = m.group(3)
        if year_str:
            y = int(year_str)
            if y < 100:
                y += 2000
            year = y
        else:
            year = now.year

        try:
            return datetime(year, month, day)
        except ValueError:
            continue
    return None

def _days_until(dt: datetime) -> int:
    today = datetime.now().date()
    return (dt.date() - today).days


# -----------------------------
# "Inteligência do ChatGPT"
# (chamada opcional: só para emails não-óbvios)
# -----------------------------

def _openai_chat(prompt: str) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    # Evita quebrar caso openai não esteja instalado / não queira usar agora
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None

    client = OpenAI(api_key=api_key)

    # Modelo: use um pequeno e barato. Se você trocar depois, só altere aqui.
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Você classifica emails por importância pessoal. Responda APENAS em JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception:
        return None


@dataclass
class ClassifiedEmail:
    subject: str
    sender: str
    snippet: str
    priority: str  # "ALTA", "MEDIA", "BAIXA", "IGNORAR"
    score: int     # 0-100
    one_liner: str
    actions: List[str]
    due_date: Optional[datetime] = None


# -----------------------------
# Classificação (regra + LLM opcional)
# -----------------------------

def classify_email(email: Dict[str, Any]) -> ClassifiedEmail:
    subject = _get(email, "subject", default="(sem assunto)")
    sender = _get(email, "from", "sender", "from_email", default="(remetente desconhecido)")
    snippet = _get(email, "snippet", "body", default="")

    blob = f"{subject}\n{sender}\n{snippet}"

    # 1) Ignorar infra/alertas
    if _matches_any(blob, IGNORE_SUBJECT_PATTERNS):
        return ClassifiedEmail(
            subject=subject,
            sender=sender,
            snippet=snippet,
            priority="IGNORAR",
            score=0,
            one_liner="Alerta/monitoramento de sistema (ignorado por regra).",
            actions=["Ignorar/arquivar (não é prioridade pessoal)."],
        )

    # 2) Baixa prioridade (newsletters, promo, social)
    if _matches_any(blob, LOW_PRIORITY_PATTERNS):
        return ClassifiedEmail(
            subject=subject,
            sender=sender,
            snippet=snippet,
            priority="BAIXA",
            score=15,
            one_liner="Conteúdo promocional/newsletter/social.",
            actions=["Arquivar ou mover para pasta/label de promo/newsletter."],
        )

    # 3) Alta prioridade por palavras-chave (banco/contas/escola/vencimentos)
    due_date = _extract_first_date(blob)
    has_due_hint = any(h in _norm(blob) for h in DUE_HINTS)
    has_high_kw = _contains_any(blob, HIGH_PRIORITY_KEYWORDS)

    if has_high_kw or (has_due_hint and due_date is not None):
        score = 85
        actions: List[str] = []

        # Ajuste por proximidade do vencimento
        if due_date is not None:
            d = _days_until(due_date)
            if d <= 0:
                score = 100
                actions.append("Verificar se está vencido hoje/atrasado e regularizar imediatamente.")
            elif d <= 2:
                score = 95
                actions.append("Agendar pagamento/ação hoje para não perder o prazo.")
            elif d <= 7:
                score = 90
                actions.append("Colocar lembrete e planejar pagamento/ação ainda nesta semana.")
            else:
                score = 85
                actions.append("Registrar na sua lista de pendências com lembrete.")

        # Ações específicas (heurísticas)
        t = _norm(blob)
        if any(k in t for k in ["fatura", "boleto", "vencimento", "a vencer", "segunda via", "2a via", "2ª via"]):
            actions.insert(0, "Abrir o email e verificar valor, vencimento e forma de pagamento.")
            actions.append("Se possível, pagar via app/banco e arquivar o comprovante.")
        if any(k in t for k in ["fraude", "suspeita", "compra não reconhecida", "compra nao reconhecida"]):
            actions.insert(0, "Abrir imediatamente: possível fraude. Bloquear/contestar no app do banco.")
        if any(k in t for k in ["escola", "colégio", "colegio", "mensalidade", "rematrícula", "rematricula", "boletim"]):
            actions.insert(0, "Abrir e checar se há prazo/ação (mensalidade, rematrícula, comunicado).")

        one_liner = "Banco/contas/escola/prazo: requer ação prática."
        if due_date is not None:
            one_liner = f"{one_liner} Data detectada: {due_date.strftime('%d/%m/%Y')}."

        # Remover duplicatas e manter curto
        actions = _dedupe_keep_order([a for a in actions if a.strip()])[:5]

        return ClassifiedEmail(
            subject=subject,
            sender=sender,
            snippet=snippet,
            priority="ALTA",
            score=min(100, score),
            one_liner=one_liner,
            actions=actions,
            due_date=due_date,
        )

    # 4) Média prioridade por tema (sem urgência clara)
    if _contains_any(blob, MEDIUM_PRIORITY_KEYWORDS):
        return ClassifiedEmail(
            subject=subject,
            sender=sender,
            snippet=snippet,
            priority="MEDIA",
            score=55,
            one_liner="Possivelmente relevante, mas sem urgência clara.",
            actions=["Ler rapidamente e decidir se vira pendência/encaminhamento."],
        )

    # 5) Zona cinzenta → usar LLM para decidir se é banco/conta/escola/prazo
    llm = _classify_with_llm(subject, sender, snippet)
    if llm is not None:
        return llm

    # 6) Fallback: baixa por padrão (triagem manual)
    return ClassifiedEmail(
        subject=subject,
        sender=sender,
        snippet=snippet,
        priority="BAIXA",
        score=25,
        one_liner="Sem sinais fortes de ser banco/conta/escola/prazo.",
        actions=["Arquivar ou revisar depois se tiver tempo."],
    )


def _classify_with_llm(subject: str, sender: str, snippet: str) -> Optional[ClassifiedEmail]:
    # Evita enviar textos longos demais
    snippet_short = (snippet or "")[:800]

    prompt = {
        "tarefa": "Classifique o email para prioridade pessoal do usuário.",
        "regras": {
            "ALTA": "banco, fatura, boleto, contas, cobrança, aviso de vencimento, escola, rematrícula, prazo com ação necessária",
            "MEDIA": "relevante mas sem prazo/ação imediata clara",
            "BAIXA": "promoções, newsletters, social, assuntos não essenciais",
            "IGNORAR": "alertas de infraestrutura/monitoramento (Render/Railway/incident/status/error/failure/etc)",
        },
        "email": {"subject": subject, "from": sender, "snippet": snippet_short},
        "responda_em_json": {
            "priority": "ALTA|MEDIA|BAIXA|IGNORAR",
            "one_liner": "string curta",
            "actions": ["lista curta de ações práticas, máx 4"],
        },
    }

    raw = _openai_chat(json.dumps(prompt, ensure_ascii=False))
    if not raw:
        return None

    try:
        data = json.loads(raw)
        pr = str(data.get("priority", "")).upper().strip()
        one = str(data.get("one_liner", "")).strip() or "Classificado pelo modelo."
        acts = data.get("actions", [])
        if not isinstance(acts, list):
            acts = []
        acts = [str(a).strip() for a in acts if str(a).strip()]
        acts = _dedupe_keep_order(acts)[:4]

        if pr not in {"ALTA", "MEDIA", "BAIXA", "IGNORAR"}:
            return None

        score_map = {"IGNORAR": 0, "BAIXA": 25, "MEDIA": 55, "ALTA": 85}
        return ClassifiedEmail(
            subject=subject,
            sender=sender,
            snippet=snippet,
            priority=pr,
            score=score_map[pr],
            one_liner=one,
            actions=acts if acts else ["Ler e decidir ação."],
        )
    except Exception:
        return None


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            out.append(it)
            seen.add(it)
    return out


# -----------------------------
# Agrupamento e resumo final
# -----------------------------

def group_by_subject(emails: List[ClassifiedEmail]) -> Dict[str, Tuple[ClassifiedEmail, int]]:
    """
    Junta emails idênticos (mesmo subject normalizado).
    Retorna dict: key -> (email_representante, contagem)
    """
    grouped: Dict[str, Tuple[ClassifiedEmail, int]] = {}
    for e in emails:
        key = re.sub(r"\s+", " ", _norm(e.subject))
        if key in grouped:
            rep, n = grouped[key]
            # Mantém o "melhor" (maior score) como representante
            if e.score > rep.score:
                grouped[key] = (e, n + 1)
            else:
                grouped[key] = (rep, n + 1)
        else:
            grouped[key] = (e, 1)
    return grouped


def build_summary(emails: List[Dict[str, Any]]) -> str:
    classified = [classify_email(e) for e in emails]

    # Tirar "IGNORAR" do relatório (se quiser ver, troque aqui para manter em BAIXA)
    kept = [c for c in classified if c.priority != "IGNORAR"]

    grouped = group_by_subject(kept)
    items = []
    for _, (rep, count) in grouped.items():
        items.append((rep, count))

    # Ordenar por score desc, depois por prioridade
    items.sort(key=lambda x: (x[0].score, x[1]), reverse=True)

    high = [(e, c) for e, c in items if e.priority == "ALTA"]
    med = [(e, c) for e, c in items if e.priority == "MEDIA"]
    low = [(e, c) for e, c in items if e.priority == "BAIXA"]

    lines: List[str] = []
    if high:
        lines.append("Emails com prioridade ALTA\n")
        lines.extend(_format_block(high))
    if med:
        if lines:
            lines.append("")
        lines.append("Emails com prioridade MÉDIA\n")
        lines.extend(_format_block(med))
    if low:
        if lines:
            lines.append("")
        lines.append("Emails de BAIXA prioridade (ação opcional)\n")
        lines.extend(_format_block(low, include_actions=False))

    if not lines:
        return "Nada relevante encontrado (banco/contas/escola/prazos)."

    return "\n".join(lines).strip()


def _format_block(block: List[Tuple[ClassifiedEmail, int]], include_actions: bool = True) -> List[str]:
    out: List[str] = []
    for idx, (e, count) in enumerate(block, start=1):
        count_txt = f" (recebido {count}x)" if count > 1 else ""
        out.append(f"{idx}) [{e.score}/100] {e.subject}{count_txt}")
        out.append(f"- Resumo (1 linha): {e.one_liner}")
        if include_actions:
            if e.actions:
                out.append("- Ações práticas:")
                for a in e.actions:
                    out.append(f"  - {a}")
        out.append("")  # linha em branco
    if out and out[-1] == "":
        out.pop()
    return out
