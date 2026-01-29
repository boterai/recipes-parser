"""
Экстрактор данных рецептов для сайта moje-grne.com
"""

import sys
from pathlib import Path
import json
import html
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MojeGrneExtractor(BaseRecipeExtractor):
    """Экстрактор для moje-grne.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.soup.find('script', {'type': 'application/ld+json'})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                # Ищем объект Article в @graph
                for item in data.get('@graph', []):
                    if item.get('@type') == 'Article':
                        headline = item.get('headline')
                        if headline:
                            # Сначала декодируем HTML entities
                            headline = html.unescape(headline)
                            # Убираем все виды кавычек (различные Unicode кавычки)
                            headline = re.sub(r'[„""\u201C\u201D\u201E\u201F«»''\u2018\u2019]', '', headline)
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            text = h1.get_text()
            # Убираем все виды кавычек
            text = re.sub(r'[„""\u201C\u201D\u201E\u201F«»''\u2018\u2019]', '', text)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # На moje-grne.com нет отдельного описания, возвращаем None
        # (meta description содержит название блюда или сгенерированный текст)
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[Dict[str, any]]:
        """
        Парсинг одной строки ингредиента
        Примеры:
        - "250g mekog brašna T-400" -> {name: "meko brašno T-400", amount: 250, units: "g"}
        - "1 kašičica soli" -> {name: "sol", amount: 1, units: "kašičica"}
        """
        line = line.strip()
        if not line:
            return None
        
        # Паттерн: число + единица измерения (опционально) + название
        # Поддерживаемые единицы: g, ml, kg, l, kašičica, kašika, kašike, glavice, srednje, šolja, čaša, шт., pune kašike
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|ml|kg|l|kašičica|kašičice|kašika|kašike|glavice|glavica|srednje|šolja|čaša|шт\.|pune\s+kašike)?\s*(.+)$'
        
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            amount = match.group(1).replace(',', '.')
            units = match.group(2) if match.group(2) else None
            name = match.group(3).strip()
            
            return {
                "name": name,
                "units": units,
                "amount": amount
            }
        
        # Если паттерн не совпал, возможно это ингредиент без количества
        # Пример: "so", "biber"
        return {
            "name": line,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        ingredients = []
        
        # Ищем параграф с "Potreban materijal:" или "Sastojci:"
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True).lower()
            
            if 'potreban materijal' in text or 'sastojci' in text:
                # Собираем все ингредиенты из последующих параграфов до "Priprema:"
                j = i + 1
                while j < len(paragraphs):
                    para_text = paragraphs[j].get_text(strip=True).lower()
                    
                    # Прерываем, если встретили "Priprema:" или "Postupak:"
                    if 'priprema' in para_text or 'postupak' in para_text:
                        break
                    
                    # Проверяем, содержит ли параграф ингредиенты (с <br> тегами)
                    ing_para = paragraphs[j]
                    ing_html = ing_para.decode_contents()
                    
                    # Если есть <br> теги, это ингредиенты
                    if re.search(r'<br\s*/?>', ing_html, re.IGNORECASE):
                        # Разбиваем по <br> тегам
                        lines = re.split(r'<br\s*/?>', ing_html, flags=re.IGNORECASE)
                        
                        for line in lines:
                            # Убираем HTML теги из строки
                            clean_line = re.sub(r'<[^>]+>', '', line).strip()
                            if clean_line:
                                ingredient = self.parse_ingredient_line(clean_line)
                                if ingredient:
                                    ingredients.append(ingredient)
                    else:
                        # Это может быть заголовок подсекции (например, "premaz" или "susam za posip")
                        # Проверяем, является ли это коротким текстом без чисел
                        para_text = paragraphs[j].get_text(strip=True)
                        if para_text and len(para_text) < 30 and not re.search(r'\d', para_text):
                            # Это заголовок подсекции, пропускаем его
                            # Но если это единственное слово/фраза, оно может быть ингредиентом без количества
                            # Например, "susam za posip"
                            if j + 1 < len(paragraphs):
                                next_para = paragraphs[j + 1]
                                next_html = next_para.decode_contents()
                                # Если следующий параграф не содержит <br>, это ингредиент без количества
                                if not re.search(r'<br\s*/?>', next_html, re.IGNORECASE):
                                    next_text = next_para.get_text(strip=True).lower()
                                    if not ('priprema' in next_text or 'postupak' in next_text):
                                        # Добавляем как ингредиент без количества
                                        ingredient = {
                                            "name": para_text,
                                            "units": None,
                                            "amount": None
                                        }
                                        ingredients.append(ingredient)
                    
                    j += 1
                
                break
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Ищем параграф с "Priprema:" или "Postupak:"
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True).lower()
            
            if 'priprema' in text or 'postupak' in text:
                # Собираем все последующие параграфы до конца или до специального маркера
                instructions_parts = []
                j = i + 1
                
                while j < len(paragraphs):
                    para_text = paragraphs[j].get_text(strip=True)
                    
                    # Прерываем, если встретили маркеры конца рецепта
                    lower_text = para_text.lower()
                    if any(marker in lower_text for marker in ['recept', 'izvor', 'napomena:', 'savet:']):
                        # Но если это "Napomena:", сохраним это для extract_notes
                        if 'napomena:' in lower_text or 'savet:' in lower_text:
                            break
                        # Для других маркеров проверяем, является ли это концом
                        if para_text and len(para_text) < 150 and ('recept' in lower_text or 'izvor' in lower_text):
                            break
                    
                    if para_text:
                        instructions_parts.append(para_text)
                    
                    j += 1
                
                if instructions_parts:
                    # Объединяем все части инструкций
                    return ' '.join(instructions_parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из JSON-LD
        json_ld = self.soup.find('script', {'type': 'application/ld+json'})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                for item in data.get('@graph', []):
                    if item.get('@type') == 'Article':
                        sections = item.get('articleSection', [])
                        if sections and isinstance(sections, list):
                            # Фильтруем, оставляя только релевантные категории
                            # Убираем "Food blogosfera" и любые категории с временем или брендами
                            relevant = []
                            for s in sections:
                                if s and s not in ['Food blogosfera']:
                                    # Пропускаем категории с временем (например, "30 minuta - Lupo Marshall")
                                    if 'minut' not in s.lower() and '-' not in s:
                                        relevant.append(s)
                            if relevant:
                                return ', '.join(relevant)
            except (json.JSONDecodeError, KeyError):
                pass
        
        return None
    
    def extract_time_from_instructions(self, instructions: str, time_type: str = 'cook') -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        Ищет паттерны типа "45 minuta", "30 minuta", "1 sat", "20 minuta"
        Для cook_time приоритет отдается времени около слова "peći" (печь)
        """
        if not instructions:
            return None
        
        # Для времени приготовления ищем упоминания около "peći" (печь)
        if time_type == 'cook':
            # Ищем паттерн "peći ... X minuta" или "X minuta ... peći"
            cook_pattern = r'peći[^.]*?(\d+)\s*(?:–\s*\d+\s*)?minut[ae]?|(\d+)\s*(?:–\s*\d+\s*)?minut[ae]?[^.]*?peći'
            match = re.search(cook_pattern, instructions, re.IGNORECASE)
            if match:
                minutes = match.group(1) or match.group(2)
                return f"{minutes} minuta"
        
        # Паттерны для времени
        # "45 minuta", "nekih 45 minuta", "oko 30 minuta", "20 minuta", "20 – 30 minuta"
        minute_pattern = r'(\d+)\s*(?:–\s*\d+\s*)?minut[ae]?'
        hour_pattern = r'(\d+)\s*sat[a]?'
        
        # Ищем минуты
        minute_match = re.search(minute_pattern, instructions, re.IGNORECASE)
        if minute_match:
            minutes = minute_match.group(1)
            return f"{minutes} minuta"
        
        # Ищем часы
        hour_match = re.search(hour_pattern, instructions, re.IGNORECASE)
        if hour_match:
            hours = hour_match.group(1)
            return f"{int(hours) * 60} minuta"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Пробуем найти в инструкциях упоминания о времени отстаивания/подготовки
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "ostaviti da odstoji 15 minuta"
            prep_pattern = r'odstoji\s+(?:da\s+)?(\d+)\s*minut[ae]?'
            match = re.search(prep_pattern, instructions, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minuta"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем из категории (articleSection в JSON-LD)
        # Иногда время указано там, например "30 minuta - Lupo Marshall"
        json_ld = self.soup.find('script', {'type': 'application/ld+json'})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                for item in data.get('@graph', []):
                    if item.get('@type') == 'Article':
                        sections = item.get('articleSection', [])
                        if sections and isinstance(sections, list):
                            for section in sections:
                                # Ищем паттерн типа "30 minuta - ..."
                                match = re.match(r'(\d+)\s*minut[ae]?\s*-', section, re.IGNORECASE)
                                if match:
                                    minutes = match.group(1)
                                    return f"{minutes} minuta"
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Если не нашли в категории, ищем в инструкциях
        instructions = self.extract_instructions()
        if instructions:
            return self.extract_time_from_instructions(instructions, 'cook')
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На moje-grne.com обычно не указывается общее время отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Ищем параграф с "Napomena:" или "Savet:"
        for p in paragraphs:
            text = p.get_text(strip=True)
            lower_text = text.lower()
            
            if 'napomena:' in lower_text or 'savet:' in lower_text:
                # Убираем префикс "Napomena:" или "Savet:"
                note = re.sub(r'^(napomena|savet):\s*', '', text, flags=re.IGNORECASE)
                return self.clean_text(note)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем из JSON-LD
        json_ld = self.soup.find('script', {'type': 'application/ld+json'})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                for item in data.get('@graph', []):
                    if item.get('@type') == 'Article':
                        keywords = item.get('keywords')
                        if keywords:
                            if isinstance(keywords, list):
                                # Объединяем с пробелами после запятых согласно требованиям
                                return ', '.join(keywords)
                            elif isinstance(keywords, str):
                                return keywords
            except (json.JSONDecodeError, KeyError):
                pass
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        images = []
        
        # Пробуем из JSON-LD
        json_ld = self.soup.find('script', {'type': 'application/ld+json'})
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                for item in data.get('@graph', []):
                    if item.get('@type') == 'Article':
                        thumbnail = item.get('thumbnailUrl')
                        if thumbnail:
                            images.append(thumbnail)
                    elif item.get('@type') == 'ImageObject':
                        url = item.get('url')
                        if url and url not in images:
                            images.append(url)
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Также проверяем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url not in images:
                images.append(img_url)
        
        if images:
            return ','.join(images)
        
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags()
        }


def main():
    """Точка входа для тестирования парсера"""
    # Путь к директории с preprocessed файлами
    preprocessed_dir = Path(__file__).parent.parent / 'preprocessed' / 'moje-grne_com'
    
    if preprocessed_dir.exists():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(MojeGrneExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == '__main__':
    main()
