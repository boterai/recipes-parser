"""модуль с утилитами для работы с языками"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)

LanguageCodes = {
    "en": ["en", "eng", "english", "en-GB", "en-US"],
    "ru": ["ru", "rus", "russian", "ru-RU"],
    "de": ["de", "ger", "german", "de-DE"],
    "fr": ["fr", "fre", "french", "fr-FR"],
    "es": ["es", "spa", "spanish", "es-ES"],
    "it": ["it", "ita", "italian", "it-IT"],
    "tr": ["tr", "tur", "turkish", "tr-TR"],
}

def validate_and_normalize_language(language: str) -> Optional[str]:
        """
        Проверяет язык в ключах и значениях вариаций, возвращает нормализованный код
        
        Args:
            language: Код или название языка для проверки
            
        Returns:
            Нормализованный код языка (например 'en', 'ru') или None если не найден
        """
        lang_lower = language.lower().strip()
        
        # Шаг 1: Проверяем в ключах (основные коды: en, ru, de, etc.)
        if lang_lower in LanguageCodes.keys():
            logger.info(f"Язык '{language}' найден в основных кодах: {lang_lower}")
            return lang_lower
        
        # Шаг 2: Проверяем в значениях вариаций каждого языка
        for main_code, variations in LanguageCodes.items():
            variations_lower = [v.lower() for v in variations]
            if lang_lower in variations_lower:
                logger.info(f"Язык '{language}' найден в вариациях '{main_code}': {variations}")
                return main_code
        
        # Язык не найден
        logger.error(f"Язык '{language}' не поддерживается")
        return None