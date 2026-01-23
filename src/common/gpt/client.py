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
import asyncio
import aiohttp
from src.common.gpt.clean_response import GPTJsonExtractor
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
        """
        # 1. Удалить/экранировать кавычки только внутри строковых значений,
        #    не трогая ключи и синтаксис JSON.
        def clean_string_value(match: re.Match) -> str:
            prefix = match.group(1)      # "key": "
            value = match.group(2)       # raw string value
            # Убираем неэкранированные кавычки внутри значения
            cleaned = re.sub(r'(?<!\\)"', '', value)
            return f'{prefix}{cleaned}"'

        text = re.sub(
            r'("(?P<key>[^"]+)"\s*:\s*")(?P<val>(?:\\.|[^"\\])*)"',  # ключ + строковое значение
            clean_string_value,
            text
        )

        return text
    
    async def async_request(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = GPT_MODEL_MINI,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: int = 30,
        retry_attempts: int = 3,
        response_schema: Optional[dict] = None
    ) -> dict[str, Any]:
        """
        Асинхронный запрос к ChatGPT API с повторными попытками
        
        Args:
            system_prompt: Системный промпт (роль ассистента)
            user_prompt: Пользовательский промпт (задание)
            model: Модель GPT для использования
            temperature: Температура генерации (0-1)
            max_tokens: Максимальное количество токенов в ответе
            timeout: Таймаут запроса в секундах
            retry_attempts: Количество попыток при ошибках
            response_schema: Схема валидации ответа (опционально), помогает вычищать ответ от двойных кавычек и лишних символов 
            
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
        
        last_exception = None
        
        # Настройка прокси для aiohttp
        connector = None
        if self.proxy:
            connector = aiohttp.TCPConnector()
        
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        
        for attempt in range(retry_attempts):
            try:
                async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
                    async with session.post(
                        self.api_url,
                        headers=headers,
                        json=payload,
                        proxy=self.proxy if self.proxy else None
                    ) as response:
                        response.raise_for_status()
                        response_data = await response.json()
                        result_text = response_data['choices'][0]['message']['content'].strip()
                        
                        # Очистка от markdown форматирования
                        result_text = self._clean_markdown(result_text)
                        result = json.loads(result_text)
                        
                        return result
                
            except json.JSONDecodeError as e:
                # если есть схема - пробуем ручной парсинг
                if response_schema:
                    try:
                        logger.info("Попытка ручного парсинга JSON от GPT с использованием схемы")
                        extractor = GPTJsonExtractor(response_schema)
                        result = extractor.extract_all_values(result_text)
                        return result
                    except Exception as inner_e:
                        logger.error(f"Ошибка ручного парсинга JSON от GPT: {inner_e}")
                        logger.error(f"Ответ GPT для ручного парсинга: {result_text if 'result_text' in locals() else 'N/A'}")
                        last_exception = inner_e
                        break
                logger.error(f"Ошибка парсинга JSON от GPT: {e}")
                logger.error(f"Ответ GPT: {result_text if 'result_text' in locals() else 'N/A'}")
                last_exception = e
                # JSON ошибки не повторяем
                break
                
            except aiohttp.ClientResponseError as e:
                # Если 403 (Forbidden) - не повторяем, это ошибка авторизации
                if e.status == 403:
                    logger.error("Ошибка 403 (Forbidden): проверьте API ключ")
                    raise
                
                last_exception = e
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: 2^attempt секунд (1, 2, 4, 8...)
                    delay = 2 ** attempt
                    logger.warning(f"HTTP ошибка {e.status}: попытка {attempt + 1}/{retry_attempts}. Повтор через {delay}с...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Ошибка HTTP запроса к GPT после {retry_attempts} попыток: {e}")
                    
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt < retry_attempts - 1:
                    delay = 2 ** attempt
                    logger.warning(f"Ошибка запроса к GPT: попытка {attempt + 1}/{retry_attempts}. Повтор через {delay}с...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Ошибка запроса к GPT после {retry_attempts} попыток: {e}")
                    
            except Exception as e:
                logger.error(f"Неожиданная ошибка запроса к GPT: {e}")
                last_exception = e
                break
        
        # Если дошли сюда - все попытки исчерпаны
        raise last_exception if last_exception else Exception("Неизвестная ошибка запроса к GPT")
    
    def request(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = GPT_MODEL_MINI,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        timeout: int = 30,
        retry_attempts: int = 3,
        response_schema: Optional[dict] = None
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
            response_schema: Схема валидации ответа (опционально), помогает вычищать ответ от двойных кавычек и лишних символов
            
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
                result = json.loads(result_text)
                
                return result
                
            except json.JSONDecodeError as e:
                # если есть схема - пробуем ручной парсинг
                if response_schema:
                    try:
                        logger.info("Попытка ручного парсинга JSON от GPT с использованием схемы")
                        extractor = GPTJsonExtractor(response_schema)
                        result = extractor.extract_all_values(result_text)
                        return result
                    except Exception as inner_e:
                        logger.error(f"Ошибка ручного парсинга JSON от GPT: {inner_e}")
                        logger.error(f"Ответ GPT для ручного парсинга: {result_text if 'result_text' in locals() else 'N/A'}")
                        last_exception = inner_e
                        break
                logger.error(f"Ошибка парсинга JSON от GPT: {e}")
                logger.error(f"Ответ GPT: {result_text if 'result_text' in locals() else 'N/A'}")
                last_exception = e
                # JSON ошибки не повторяем
                break
                
            except requests.exceptions.HTTPError as e:
                # Если 403 (Forbidden) - не повторяем, это ошибка авторизации
                if hasattr(e.response, 'status_code') and e.response.status_code == 403:
                    logger.error("Ошибка 403 (Forbidden): проверьте API ключ")
                    raise
                
                last_exception = e
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: 2^attempt секунд (1, 2, 4, 8...)
                    delay = 2 ** attempt
                    logger.warning(f"HTTP ошибка {e.response.status_code if hasattr(e, 'response') else 'N/A'}: попытка {attempt + 1}/{retry_attempts}. Повтор через {delay}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"Ошибка HTTP запроса к GPT после {retry_attempts} попыток: {e}")
                    
            except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
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

if __name__ == "__main__":
    client = GPTClient()
    data = '{"dish_name": "Crushed Crispy Oven-Baked Potatoes", "description": "Crushed crispy oven-baked potatoes are something in between boiled and roasted (we use this expression without a negative connotation, just to describe the essence of the dish, its texture). Tender on the inside but crispy on the outside. It resembles either potato pancakes or hash browns, but turns out softer than classic hash browns and more interesting than regular baked potatoes. The secret lies in crushing boiled potatoes, turning them into thick flat cakes with jagged edges, and then baking them until crispy. Crushed potatoes baked in the oven will surprise both kids and adults, and are very easy to make!", "ingredients": ["potatoes", "olive oil", "dried garlic", "dried rosemary", "salt", "ground black pepper", "sweet paprika"], "tags": ["potatoes", "oven dishes", "side dish", "oven-baked potatoes"], "category": "main course", "instructions": "Step 1: Thoroughly scrub the potatoes with a brush. Choose potatoes of roughly the same size so they cook evenly. In a large pot, bring salted water to a boil. Add the potatoes to the boiling water and cook for 20-25 minutes after it starts boiling, until they are soft but not falling apart. The potatoes should be easily pierced with a fork. Step 2: Preheat the oven to 220°C. Line a baking sheet with parchment paper and grease it with 1 tbsp of olive oil. Place the boiled potatoes on the baking sheet. Take a wooden masher or a cup and gently press down on each potato to flatten them to a thickness of 2-2.5 cm. Step 3: In a small bowl, mix the remaining olive oil with dried garlic, rosemary, paprika, salt, and pepper. Generously spread this flavorful mixture on each potato "pancaked", making sure the oil gets into all the cracks. Step 4: Place the baking sheet in the preheated oven for 15-20 minutes. Do not flip the potatoes during cooking. Check for doneness by the golden-brown crispy edges and surface. For extra crispiness, you can turn on the grill for 3-4 minutes at the end of cooking. Step 5: The crushed, oven-baked potatoes are ready. Remove from the oven and let them rest for 2-3 minutes. Serve hot, optionally sprinkled with coarse sea salt and fresh rosemary. Perfect with sour cream or Greek yogurt-based sauces."}'
    data = client._normalize_json(data)
    js = json.loads(data)
    print("Before normalization:", js)