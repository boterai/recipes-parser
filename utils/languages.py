"""модуль с утилитами для работы с языками"""

from typing import Optional
import logging
import re

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
    "fr": ["fr", "fre", "french", "fr-FR", "fr-CA"],
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

def validate_and_normalize_language(language: str) -> str:
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
        return lang_lower
    
    # Шаг 2: Проверяем в значениях вариаций каждого языка
    for main_code, variations in LanguageCodes.items():
        variations_lower = [v.lower() for v in variations]
        if lang_lower in variations_lower:
            return main_code
    
    # Язык не найден
    logger.error(f"Язык '{language}' не поддерживается, возвращаем исходное значение")
    return lang_lower

COOKIE_KEYWORDS = [
        # English
        'accept', 'allow', 'agree', 'consent', 'ok', 'got it', 'i understand',
        'accept all', 'allow all', 'agree and close', 'accept cookies', 'continue',
        # Italian
        'accetta', 'accetto', 'consenti', 'consento', 'accetta tutti',
        'accettare', 'consenso', 'va bene', 'ok', 'capito',
        # German  
        'akzeptieren', 'zustimmen', 'einverstanden', 'alle akzeptieren', 'verstanden',
        # French
        'accepter', 'autoriser', "j'accepte", 'tout accepter', "d'accord", 'continuer',
        # Spanish
        'aceptar', 'permitir', 'de acuerdo', 'aceptar todo', 'aceptar todas',
        # Polish
        'akceptuj', 'zgadzam', 'zezwól', 'akceptuję wszystkie', 'rozumiem',
        # Dutch
        'accepteren', 'toestaan', 'akkoord', 'alle accepteren', 'begrepen',
        # Swedish
        'tillåt', 'godkänn', 'acceptera', 'samtycke', 'tillåt alla', 'godkänn alla',
        # Russian
        'принять', 'согласен', 'разрешить', 'принять все', 'понятно',
        # Portuguese
        'aceitar', 'permitir', 'concordo', 'aceitar todos', 'aceitar tudo', 'está bem',
        # Japanese
        '同意', '承諾', '許可', 'すべて許可', 'すべて同意', 'わかりました', 'OK',
        # Korean
        '동의', '수락', '허용', '모두 수락', '모두 허용', '확인', '알겠습니다',
        # Chinese (Simplified)
        '接受', '同意', '允许', '全部接受', '全部同意', '我知道了', '确定',
        # Arabic
        'موافق', 'قبول', 'أوافق', 'قبول الكل', 'السماح', 'فهمت',
        # Hindi
        'स्वीकार', 'अनुमति', 'सहमत', 'सभी स्वीकार करें', 'ठीक है',
        # Turkish
        'kabul et', 'izin ver', 'kabul ediyorum', 'tümünü kabul et', 'anladım', 'tamam',
        # Norwegian
        'godta', 'tillat', 'godkjenn', 'godta alle', 'aksepter', 'jeg forstår',
        # Finnish
        'hyväksy', 'salli', 'ymmärrän', 'hyväksy kaikki', 'ok', 'selvä',
        # Greek
        'αποδοχή', 'συναίνεση', 'αποδέχομαι', 'αποδοχή όλων', 'κατάλαβα',
        # Hebrew
        'אישור', 'אני מסכים', 'הבנתי', 'אשר הכל', 'אישור הכל',
        # Thai
        'ยอมรับ', 'อนุญาต', 'ตกลง', 'ยอมรับทั้งหมด', 'เข้าใจแล้ว',
        # Vietnamese
        'chấp nhận', 'đồng ý', 'cho phép', 'chấp nhận tất cả', 'tôi hiểu',
        # Indonesian
        'terima', 'setuju', 'izinkan', 'terima semua', 'saya mengerti', 'oke',
        # Filipino (Tagalog)
        'tanggapin', 'payagan', 'sumasang-ayon', 'tanggapin lahat', 'naiintindihan ko',
        # Czech
        'přijmout', 'povolit', 'souhlasím', 'přijmout vše', 'rozumím',
        # Hungarian
        'elfogad', 'engedélyez', 'egyetértek', 'mindet elfogad', 'értem',
        # Romanian
        'accept', 'permite', 'sunt de acord', 'acceptă toate', 'înțeleg',
        # Ukrainian
        'прийняти', 'дозволити', 'згоден', 'прийняти все', 'зрозуміло',
        # Serbian
        'prihvati', 'dozvoli', 'slažem se', 'prihvati sve', 'razumem',
        # Croatian
        'prihvati', 'dopusti', 'slažem se', 'prihvati sve', 'razumijem',
        # Bulgarian
        'приемам', 'разрешавам', 'съгласен', 'приеми всички', 'разбирам',
        # Slovak
        'prijať', 'povoliť', 'súhlasím', 'prijať všetko', 'rozumiem',
        # Slovenian
        'sprejmi', 'dovoli', 'strinjam se', 'sprejmi vse', 'razumem',
        # Lithuanian
        'priimti', 'leisti', 'sutinku', 'priimti viską', 'suprantu',
        # Estonian
        'nõustu', 'luba', 'olen nõus', 'nõustu kõigiga', 'sain aru',
        # Danish
        'accepter', 'tillad', 'godkend', 'accepter alle', 'forstået'
    ]
        
# Находим все возможные элементы-кнопки
COOKIE_SELECTORS = [
    'button',
    'a[role="button"]',
    'div[role="button"]', 
    'span[role="button"]',
    'input[type="button"]',
    'input[type="submit"]',
    'a.button',
    'div.button',
    '[class*="button"]',
    '[class*="btn"]',
    '[id*="accept"]',
    '[id*="Accept"]',
    '[id*="consent"]',
    '[id*="Consent"]',
    '[id*="cookie"]',
    '[id*="Cookie"]',
    '[id*="allow"]',
    '[id*="Allow"]',
    '[id*="agree"]',
    '[id*="Agree"]',
    '[class*="accept"]',
    '[class*="Accept"]',
    '[class*="consent"]',
    '[class*="Consent"]',
    '[class*="cookie"]',
    '[class*="Cookie"]',
    '[class*="allow"]',
    '[class*="Allow"]',
    '[class*="agree"]',
    '[class*="Agree"]',
    # Специфичные для популярных cookie-баннеров
    '[id*="CybotCookiebot"]',
    '[id*="OptinAllow"]',
    '[id*="AllowAll"]',
    '[id*="onetrust"]',
    '[id*="OneTrust"]',
    '[class*="onetrust"]',
    '[class*="OneTrust"]',
    '[id*="cookieConsent"]',
    '[class*="cookieConsent"]',
    '[id*="gdpr"]',
    '[id*="GDPR"]',
    '[class*="gdpr"]',
    '[class*="GDPR"]',
    # ARIA роли и data-атрибуты
    '[aria-label*="accept"]',
    '[aria-label*="cookie"]',
    '[aria-label*="consent"]',
    '[data-testid*="cookie"]',
    '[data-testid*="consent"]',
    '[data-testid*="accept"]',
    '[data-action*="accept"]',
    '[data-action*="consent"]',
    # Дополнительные общие паттерны
    '.cookie-accept',
    '.cookie-consent',
    '.cookie-allow',
    '.consent-accept',
    '.consent-button',
    '#cookie-accept',
    '#cookie-consent',
    '#accept-cookies',
    '#accept-all'
]