import os
from typing import List, Dict
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def build_summary(emails: List[Dict]) -> str:
    if not emails:
        return "📭 Nenhum email relevante no período."

    text = ""
    for e in emails:
        text += (
            f"FROM: {e['from']}\n"
            f"SUBJECT: {e['subject']}\n"
            f"SNIPPET: {e.get('snippet', '')}\n\n"
        )

    prompt = f"""
Você é um assistente executivo.
Selecione os emails realmente importantes.
Resuma cada um em 1 linha.
Sugira ações práticas.

Emails:
{text}
"""

    resp = client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    return resp.output_text
