import time
from gmail_client import list_recent_emails
from summarizer import build_summary
from telegram_sender import send_telegram_message


# Intervalo entre execuções (em segundos)
# Exemplo: 3600 = 1 hora
CHECK_INTERVAL_SECONDS = 3600


def main():
    print("BOOT: worker loop started")

    while True:
        try:
            # 1) Buscar emails recentes
            emails = list_recent_emails(max_results=20)

            if not emails:
                print("Nenhum email encontrado.")
            else:
                # 2) Construir resumo inteligente via ChatGPT
                summary_text = build_summary(emails)

                # 3) Enviar para o Telegram
                if summary_text:
                    send_telegram_message(summary_text)
                    print("Resumo enviado para o Telegram.")
                else:
                    print("Resumo vazio, nada enviado.")

        except Exception as e:
            # Nunca deixar o worker morrer
            print("Erro no loop principal:", str(e))

        # 4) Aguarda até a próxima execução
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
