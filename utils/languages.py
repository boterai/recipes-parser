"""модуль с утилитами для работы с языками"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 35 популярных языков для перевода
POPULAR_LANGUAGES = [
    "Spanish", "French", "German", "Italian", "Portuguese", 
    "Russian", "Japanese", "Korean", "Chinese", "Arabic",
    "Hindi", "Turkish", "Polish", "Dutch", "Swedish",
    "Danish", "Norwegian", "Finnish", "Greek", "Hebrew",
    "Thai", "Vietnamese", "Indonesian", "Filipino", "Czech",
    "Hungarian", "Romanian", "Ukrainian", "Serbian", "Croatian",
    "Bulgarian", "Slovak", "Slovenian", "Lithuanian", "Estonian"
]

LanguageCodes = {
    "en": ["en", "eng", "english", "en-GB", "en-US"],
    "ru": ["ru", "rus", "russian", "ru-RU"],
    "de": ["de", "ger", "german", "de-DE"],
    "fr": ["fr", "fre", "french", "fr-FR"],
    "es": ["es", "spa", "spanish", "es-ES"],
    "it": ["it", "ita", "italian", "it-IT"],
    "tr": ["tr", "tur", "turkish", "tr-TR"],
    "pt": ["pt", "por", "portuguese", "pt-PT", "pt-BR"],
    "ja": ["ja", "jpn", "japanese", "ja-JP"],
    "ko": ["ko", "kor", "korean", "ko-KR"],
    "zh": ["zh", "chi", "chinese", "zh-CN", "zh-TW"],
    "ar": ["ar", "ara", "arabic", "ar-SA"],
    "hi": ["hi", "hin", "hindi", "hi-IN"],
    "pl": ["pl", "pol", "polish", "pl-PL"],
    "nl": ["nl", "dut", "dutch", "nl-NL"],
    "sv": ["sv", "swe", "swedish", "sv-SE"],
    "da": ["da", "dan", "danish", "da-DK"],
    "no": ["no", "nor", "norwegian", "no-NO", "nb-NO"],
    "fi": ["fi", "fin", "finnish", "fi-FI"],
    "el": ["el", "gre", "greek", "el-GR"],
    "he": ["he", "heb", "hebrew", "he-IL"],
    "th": ["th", "tha", "thai", "th-TH"],
    "vi": ["vi", "vie", "vietnamese", "vi-VN"],
    "id": ["id", "ind", "indonesian", "id-ID"],
    "tl": ["tl", "fil", "filipino", "tl-PH"],
    "cs": ["cs", "cze", "czech", "cs-CZ"],
    "hu": ["hu", "hun", "hungarian", "hu-HU"],
    "ro": ["ro", "rum", "romanian", "ro-RO"],
    "uk": ["uk", "ukr", "ukrainian", "uk-UA"],
    "sr": ["sr", "srp", "serbian", "sr-RS"],
    "hr": ["hr", "hrv", "croatian", "hr-HR"],
    "bg": ["bg", "bul", "bulgarian", "bg-BG"],
    "sk": ["sk", "slo", "slovak", "sk-SK"],
    "sl": ["sl", "slv", "slovenian", "sl-SI"],
    "lt": ["lt", "lit", "lithuanian", "lt-LT"],
    "et": ["et", "est", "estonian", "et-EE"],
}

# Маппинг названий языков на коды для POPULAR_LANGUAGES
LANGUAGE_NAME_TO_CODE = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Russian": "ru",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese": "zh",
    "Arabic": "ar",
    "Hindi": "hi",
    "Turkish": "tr",
    "Polish": "pl",
    "Dutch": "nl",
    "Swedish": "sv",
    "Danish": "da",
    "Norwegian": "no",
    "Finnish": "fi",
    "Greek": "el",
    "Hebrew": "he",
    "Thai": "th",
    "Vietnamese": "vi",
    "Indonesian": "id",
    "Filipino": "tl",
    "Czech": "cs",
    "Hungarian": "hu",
    "Romanian": "ro",
    "Ukrainian": "uk",
    "Serbian": "sr",
    "Croatian": "hr",
    "Bulgarian": "bg",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Lithuanian": "lt",
    "Estonian": "et",
}

def convert_language_name_to_code(language_name: str) -> Optional[str]:
    """
    Конвертирует название языка в двухбуквенный ISO код
    
    Args:
        language_name: Название языка (например "Spanish", "French", "Russian")
        
    Returns:
        Двухбуквенный код языка (например "es", "fr", "ru") или None если не найден
        
    Examples:
        >>> convert_language_name_to_code("Spanish")
        "es"
        >>> convert_language_name_to_code("Russian")
        "ru"
        >>> convert_language_name_to_code("Unknown")
        None
    """
    # Сначала пробуем точное совпадение
    code = LANGUAGE_NAME_TO_CODE.get(language_name)
    if code:
        return code
    
    # Если не нашли, пробуем case-insensitive поиск
    language_lower = language_name.lower().strip()
    for name, code in LANGUAGE_NAME_TO_CODE.items():
        if name.lower() == language_lower:
            return code
    
    # Если всё ещё не нашли, пробуем через validate_and_normalize_language
    # (на случай если передали уже код или вариацию)
    normalized = validate_and_normalize_language(language_name)
    if normalized:
        return normalized
    
    logger.warning(f"Не удалось конвертировать название '{language_name}' в код языка")
    return None

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