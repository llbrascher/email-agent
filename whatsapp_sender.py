import time
import pywhatkit as kit

def send_whatsapp_message(phone_e164: str, message: str) -> None:
    """
    phone_e164: formato E.164, ex: +5541999999999
    """
    kit.sendwhatmsg_instantly(
        phone_e164,
        message,
        wait_time=20,     # tempo pra abrir/carregar WhatsApp Web
        tab_close=True,   # fecha a aba depois de enviar
        close_time=5
    )
    time.sleep(3)
