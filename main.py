from gmail_client import list_recent_emails
from summarizer import build_summary
from whatsapp_sender import send_whatsapp_message

PHONE = "+5541991154852"

print("Meu agente está rodando corretamente!")

emails = list_recent_emails()

summary = build_summary(emails)   # <<< AQUI o resumo nasce

print("Enviando resumo no WhatsApp...")

send_whatsapp_message(PHONE, summary)

print("Resumo enviado com sucesso!")