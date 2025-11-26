"""
Клиент для работы с OpenAI ChatGPT API
"""

import os
import logging
import json
import requests
from typing import Optional, Any
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

logger = logging.getLogger(__name__)

# OpenAI API настройки
GPT_API_KEY = os.getenv('GPT_API_KEY')
GPT_PROXY = os.getenv('PROXY', None)
GPT_MODEL_MINI = os.getenv('GPT_MODEL_MINI', 'gpt-4o-mini')
GPT_API_URL = "https://api.openai.com/v1/chat/completions"


class GPTClient:
    """Клиент для работы с ChatGPT API"""
    
    def __init__(self, api_key: Optional[str] = None, proxy: Optional[str] = None):
        """
        Инициализация клиента
        
        Args:
            api_key: API ключ OpenAI (по умолчанию из env)
            proxy: Прокси сервер (по умолчанию из env)
        """
        self.api_key = api_key or GPT_API_KEY
        self.proxy = proxy or GPT_PROXY
        self.api_url = GPT_API_URL
        
        if not self.api_key:
            raise ValueError("GPT_API_KEY не установлен")
    
    def request(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = GPT_MODEL_MINI,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: int = 30
    ) -> dict[str, Any]:
        """
        Выполнение запроса к ChatGPT API
        
        Args:
            system_prompt: Системный промпт (роль ассистента)
            user_prompt: Пользовательский промпт (задание)
            model: Модель GPT для использования
            temperature: Температура генерации (0-1)
            max_tokens: Максимальное количество токенов в ответе
            timeout: Таймаут запроса в секундах
            
        Returns:
            Распарсенный JSON ответ от GPT
            
        Raises:
            Exception: При ошибке запроса или парсинга
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                "temperature": temperature,
            }
            
            if max_tokens:
                payload["max_tokens"] = max_tokens
            
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxies
            )
            
            response.raise_for_status()
            response_data = response.json()
            result_text = response_data['choices'][0]['message']['content'].strip()
            
            # Очистка от markdown форматирования
            result_text = self._clean_markdown(result_text)
            
            # Парсинг JSON
            result = json.loads(result_text)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от GPT: {e}")
            logger.error(f"Ответ GPT: {result_text if 'result_text' in locals() else 'N/A'}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка HTTP запроса к GPT: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка запроса к GPT: {e}")
            raise
    
    def _clean_markdown(self, text: str) -> str:
        """
        Очистка текста от markdown форматирования
        
        Args:
            text: Текст для очистки
            
        Returns:
            Очищенный текст
        """
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        return text.strip()
