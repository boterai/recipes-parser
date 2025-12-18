"""
Клиент для работы с OpenAI ChatGPT API
"""
import time
import os
import logging
import json
import requests
from typing import Optional, Any
from dotenv import load_dotenv
import re
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
        
    def _normalize_json(self, text: str) -> str:
        """
        Нормализация JSON от GPT (исправление частых ошибок)
        
        Args:
            text: JSON строка от GPT
            
        Returns:
            Исправленная JSON строка
        """
        # 1. Исправить дроби (1/4 -> 0.25)
        def replace_fraction(match):
            numerator = float(match.group(1))
            denominator = float(match.group(2))
            return str(numerator / denominator)
        
        # Находим дроби в значениях amount (не в строках!)
        text = re.sub(
            r'"amount":\s*(\d+)/(\d+)',
            lambda m: f'"amount": {replace_fraction(m)}',
            text
        )
        
        # 2. Исправить дроби в строковых значениях ("1/2" -> "0.5")
        # Только если они не в кавычках как часть текста
        text = re.sub(
            r'"amount":\s*"(\d+)/(\d+)"',
            lambda m: f'"amount": "{float(m.group(1)) / float(m.group(2))}"',
            text
        )
        
        # 3. Удалить trailing commas (запятые перед закрывающими скобками)
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # 4. Исправить одинарные кавычки на двойные (если есть)
        # text = text.replace("'", '"')  # Осторожно! Может сломать текст
        
        return text
    
    def request(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = GPT_MODEL_MINI,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: int = 30,
        retry_attempts: int = 3
    ) -> dict[str, Any]:
        """
        Выполнение запроса к ChatGPT API с повторными попытками
        
        Args:
            system_prompt: Системный промпт (роль ассистента)
            user_prompt: Пользовательский промпт (задание)
            model: Модель GPT для использования
            temperature: Температура генерации (0-1)
            max_tokens: Максимальное количество токенов в ответе
            timeout: Таймаут запроса в секундах
            retry_attempts: Количество попыток при ошибках
            
        Returns:
            Распарсенный JSON ответ от GPT
            
        Raises:
            Exception: При ошибке запроса или парсинга
        """
        
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
        
        last_exception = None
        
        for attempt in range(retry_attempts):
            try:
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

                result_text = self._normalize_json(result_text)
                
                # Парсинг JSON
                result = json.loads(result_text)
                
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON от GPT: {e}")
                logger.error(f"Ответ GPT: {result_text if 'result_text' in locals() else 'N/A'}")
                last_exception = e
                # JSON ошибки не повторяем
                break
                
            except requests.exceptions.HTTPError as e:
                # Если 403 (Forbidden) - не повторяем, это ошибка авторизации
                if hasattr(e.response, 'status_code') and e.response.status_code == 403:
                    logger.error(f"Ошибка 403 (Forbidden): проверьте API ключ")
                    raise
                
                last_exception = e
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: 2^attempt секунд (1, 2, 4, 8...)
                    delay = 2 ** attempt
                    logger.warning(f"HTTP ошибка {e.response.status_code if hasattr(e, 'response') else 'N/A'}: попытка {attempt + 1}/{retry_attempts}. Повтор через {delay}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"Ошибка HTTP запроса к GPT после {retry_attempts} попыток: {e}")
                    
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < retry_attempts - 1:
                    delay = 2 ** attempt
                    logger.warning(f"Ошибка запроса к GPT: попытка {attempt + 1}/{retry_attempts}. Повтор через {delay}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"Ошибка запроса к GPT после {retry_attempts} попыток: {e}")
                    
            except Exception as e:
                logger.error(f"Неожиданная ошибка запроса к GPT: {e}")
                last_exception = e
                break
        
        # Если дошли сюда - все попытки исчерпаны
        raise last_exception if last_exception else Exception("Неизвестная ошибка запроса к GPT")
    
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
