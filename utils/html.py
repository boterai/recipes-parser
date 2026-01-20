from typing import Optional
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

def extract_text_from_html(html_path: str, max_chars: Optional[int] = 30000) -> Optional[str]:
    """
    Извлечение текста из HTML файла
    
    Args:
        html_path: Путь к HTML файлу
        
    Returns:
        Извлеченный текст или None при ошибке
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Удаление скриптов и стилей
        for script in soup(['script', 'style', 'nav', 'footer', 'header']):
            script.decompose()
        
        # Извлечение текста
        text = soup.get_text(separator='\n', strip=True)
        
        # Ограничение размера для API
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n... (текст обрезан)"
        
        return text
        
    except Exception as e:
        logger.error(f"Ошибка извлечения текста из {html_path}: {e}")
        return None