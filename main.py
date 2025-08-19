import threading
import time
import json
import websocket
import uuid
import logging
import sys

# ============== КОНФИГУРАЦИЯ ============== #
# Впишите сюда ваши данные
ACCOUNT_TOKEN = "YOUR_DISCORD_TOKEN_HERE"
GUILD_ID = "YOUR_GUILD_ID_HERE"
VOICE_CHANNEL_ID = "YOUR_VOICE_CHANNEL_ID_HERE"

# Дополнительные настройки
SELF_MUTE = False  # Заглушить ли свой микрофон
SELF_DEAF = True   # Отключить ли звук для себя
# ========================================== #

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('voice_connector.log')
    ]
)
logger = logging.getLogger('DiscordVoiceConnector')

class DiscordVoiceConnector:
    def __init__(self, token, guild_id, channel_id):
        self.token = token
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.session_id = str(uuid.uuid4())
        self.ws = None
        self.heartbeat_thread = None
        self.running = False
        self.account_tag = token[-6:] if len(token) > 6 else token
        
        # Заголовки для запросов
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
        }
        
        logger.info(f"Инициализирован коннектор для аккаунта: ...{self.account_tag}")

    def start(self):
        """Запускает подключение к голосовому каналу"""
        self.running = True
        self.connect_gateway()
        
    def stop(self):
        """Останавливает подключение"""
        self.running = False
        if self.ws:
            self.ws.close()
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2.0)
        logger.info(f"Остановлен коннектор для ...{self.account_tag}")

    def connect_gateway(self):
        """Устанавливает соединение с Discord Gateway"""
        gateway_url = "wss://gateway.discord.gg/?v=9&encoding=json"
        logger.info(f"[...{self.account_tag}] Подключение к Gateway...")
        
        self.ws = websocket.WebSocketApp(
            gateway_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Запускаем в отдельном потоке для поддержания работы
        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    def on_open(self, ws):
        """Обработчик открытия соединения"""
        logger.info(f"[...{self.account_tag}] WebSocket соединение установлено")
        
        # Формируем payload для аутентификации
        auth_payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "properties": {
                    "$os": "linux",
                    "$browser": "chrome",
                    "$device": "pc"
                },
                "presence": {
                    "status": "online",
                    "afk": False
                }
            }
        }
        ws.send(json.dumps(auth_payload))

    def on_message(self, ws, message):
        """Обработчик входящих сообщений"""
        data = json.loads(message)
        
        # Hello - содержит интервал heartbeat
        if data['op'] == 10:
            heartbeat_interval = data['d']['heartbeat_interval'] / 1000
            logger.info(f"[...{self.account_tag}] Получен Hello, интервал heartbeat: {heartbeat_interval} сек")
            
            # Запускаем heartbeat в отдельном потоке
            self.heartbeat_thread = threading.Thread(
                target=self.send_heartbeat,
                args=(ws, heartbeat_interval),
                daemon=True
            )
            self.heartbeat_thread.start()
        
        # Ready - подтверждение успешной аутентификации
        elif data.get('t') == 'READY':
            logger.info(f"[...{self.account_tag}] Аккаунт готов, подключаюсь к голосовому каналу...")
            
            # Отправляем запрос на подключение к голосовому каналу
            voice_payload = {
                "op": 4,
                "d": {
                    "guild_id": self.guild_id,
                    "channel_id": self.channel_id,
                    "self_mute": SELF_MUTE,
                    "self_deaf": SELF_DEAF
                }
            }
            ws.send(json.dumps(voice_payload))
        
        # Обновление состояния голосового канала
        elif data.get('t') == 'VOICE_STATE_UPDATE':
            if data['d'].get('channel_id') == self.channel_id:
                logger.info(f"[...{self.account_tag}] Успешно подключен к голосовому каналу")
                logger.info(f"Сервер: {self.guild_id} | Канал: {self.channel_id}")
        
        # Обновление сервера голосовой связи
        elif data.get('t') == 'VOICE_SERVER_UPDATE':
            logger.debug(f"[...{self.account_tag}] Обновление сервера голосовой связи")

    def send_heartbeat(self, ws, interval):
        """Регулярная отправка heartbeat для поддержания соединения"""
        logger.info(f"[...{self.account_tag}] Запущен heartbeat с интервалом {interval} сек")
        sequence = None
        
        while self.running:
            try:
                # Формируем heartbeat payload
                payload = {"op": 1, "d": sequence}
                ws.send(json.dumps(payload))
                logger.debug(f"[...{self.account_tag}] Отправлен heartbeat")
            except Exception as e:
                logger.error(f"[...{self.account_tag}] Ошибка отправки heartbeat: {str(e)}")
            
            # Ожидаем указанный интервал
            time.sleep(interval)

    def on_error(self, ws, error):
        """Обработчик ошибок соединения"""
        logger.error(f"[...{self.account_tag}] WebSocket ошибка: {str(error)}")

    def on_close(self, ws, close_status_code, close_msg):
        """Обработчик закрытия соединения"""
        logger.warning(f"[...{self.account_tag}] WebSocket соединение закрыто: код={close_status_code}, сообщение={close_msg}")
        
        # Пытаемся переподключиться
        if self.running:
            logger.info(f"[...{self.account_tag}] Попытка переподключения через 15 сек...")
            time.sleep(15)
            self.connect_gateway()

def main():
    """Основная функция для запуска коннектора"""
    # Проверка заполненности конфигурации
    if ACCOUNT_TOKEN == "YOUR_DISCORD_TOKEN_HERE" or \
       GUILD_ID == "YOUR_GUILD_ID_HERE" or \
       VOICE_CHANNEL_ID == "YOUR_VOICE_CHANNEL_ID_HERE":
        logger.error("Пожалуйста, заполните конфигурационные данные в начале скрипта!")
        sys.exit(1)
    
    # Создаем и запускаем коннектор
    connector = DiscordVoiceConnector(
        token=ACCOUNT_TOKEN,
        guild_id=GUILD_ID,
        channel_id=VOICE_CHANNEL_ID
    )
    
    try:
        connector.start()
        logger.info("Скрипт успешно запущен. Для остановки нажмите Ctrl+C")
        
        # Бесконечный цикл для поддержания работы программы
        while True:
            time.sleep(3600)  # Проверяем каждый час
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания, остановка...")
        connector.stop()
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        connector.stop()

if __name__ == "__main__":
    main()
