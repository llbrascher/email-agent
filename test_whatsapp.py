from whatsapp_sender import send_whatsapp_message

PHONE = "+5541991154852"  # ex: +5541999999999

send_whatsapp_message(PHONE, "✅ Teste: meu agente enviou esta mensagem pelo WhatsApp!")
print("Mensagem enviada (se o WhatsApp Web estiver logado).")
