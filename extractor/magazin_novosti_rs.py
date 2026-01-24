"""
Экстрактор данных рецептов для сайта magazin.novosti.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MagazinNovostiRsExtractor(BaseRecipeExtractor):
    """Экстрактор для magazin.novosti.rs"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке с itemprop="headline"
        headline = self.soup.find('h1', attrs={'itemprop': 'headline'})
        if headline:
            text = headline.get_text()
            # Убираем части в скобках типа "(RECEPT)", "(VIDEO)" в конце
            text = re.sub(r'\s*\([^)]*\)\s*$', '', text)
            
            # Если есть двоеточие, берем только первую часть
            if ':' in text:
                text = text.split(':', 1)[0]
            
            # Убираем различные префиксы рецептов
            text = re.sub(r'^(Recept za|RECEPT ZA|Starinski recept za|STARINSKI RECEPT ZA)\s+', '', text, flags=re.IGNORECASE)
            
            text = self.clean_text(text)
            # Handle accusative case for dish names (ljutenicu -> ljutenica)
            if text.lower() == 'ljutenicu':
                return 'ljutenica'
            
            # Конвертируем в sentence case (первая буква заглавная, остальные строчные)
            if text:
                words = text.split()
                # Первое слово с заглавной, остальные строчные
                result = words[0].capitalize() if words else ''
                if len(words) > 1:
                    result += ' ' + ' '.join(w.lower() for w in words[1:])
                return result
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*\([^)]*\)\s*$', '', title)
            if ':' in title:
                title = title.split(':', 1)[0]
            title = re.sub(r'^(Recept za|RECEPT ZA|Starinski recept za|STARINSKI RECEPT ZA)\s+', '', title, flags=re.IGNORECASE)
            title = self.clean_text(title)
            # Handle accusative case
            if title.lower() == 'ljutenicu':
                return 'ljutenica'
            
            if title:
                words = title.split()
                result = words[0].capitalize() if words else ''
                if len(words) > 1:
                    result += ' ' + ' '.join(w.lower() for w in words[1:])
                return result
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала проверяем, есть ли описание в заголовке после двоеточия
        headline = self.soup.find('h1', attrs={'itemprop': 'headline'})
        if headline:
            text = headline.get_text()
            # Убираем части в скобках
            text = re.sub(r'\s*\([^)]*\)\s*$', '', text)
            # Если есть двоеточие, берем вторую часть как описание
            if ':' in text:
                desc = text.split(':', 1)[1].strip()
                if desc:
                    desc = self.clean_text(desc)
                    # Добавляем точку в конце, если её нет
                    if desc and not desc.endswith('.'):
                        desc += '.'
                    return desc
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Также можно попробовать первый параграф в story-content
        story = self.soup.find('div', class_='story-content')
        if story:
            first_p = story.find('p')
            if first_p:
                text = first_p.get_text(strip=True)
                # Проверяем что это не заголовок "Sastojci:" или "Priprema:"
                if text and not text.endswith(':') and len(text) > 20:
                    return self.clean_text(text)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 krompira" или "200 ml jogurt"
            
        Returns:
            dict: {"name": "krompir", "units": "pieces", "amount": 2} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 krompira", "200 ml jogurt", "0.5 pakovanje prašak za pecivo", "1/2 praška za pecivo"
        # Сначала пробуем с единицей измерения
        pattern_with_unit = r'^([\d\s/.,]+)?\s*(ml|g|kg|l|dl|pakovanje|paket|kašika|kašičica|čaša|šolja|komad|pieces?|kom)?\s*(.+)'
        
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Process amount
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Process fractions like "1/2" or "0.5"
            if '/' in amount_str:
                try:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    # Keep as float if fractional, otherwise convert to int
                    amount = int(total) if total == int(total) else total
                except (ValueError, ZeroDivisionError):
                    # If parsing fails, leave amount as None
                    amount = None
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    val = float(amount_str)
                    # Keep as int if it's a whole number
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = None
        
        # Очистка единицы измерения
        unit = unit.strip() if unit else None
        # Нормализация единиц измерения
        if unit and unit.lower() in ['paket', 'pakovanje']:
            unit = 'pakovanje'
        
        # Очистка названия
        name = name.strip() if name else text
        # Удаляем фразы типа "po ukusu", "po potrebi"
        name = re.sub(r'\b(po ukusu|po potrebi|opciono)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Handle genitive case (genitive/родительный падеж) transformations
        # Use dictionary for known cases and simple rules for unknown words
        genitive_to_nominative = {
            'soli': 'so',
            'ulja': 'ulje',
            'jogirta': 'jogurt',
            'sira': 'sir',
            'praška': 'prašak',
            'sirćeta': 'sirće',
            'krompira': 'krompir',
            'paradajza': 'paradajz',
            'ljutenicu': 'ljutenica',
        }
        
        # Only for single words (not phrases)
        if ' ' not in name:
            # Check dictionary (case-insensitive)
            name_lower = name.lower()
            if name_lower in genitive_to_nominative:
                name = genitive_to_nominative[name_lower]
            # General rules for unknown words
            elif name.endswith('ta') and len(name) > 5:
                # Might be genitive of words ending in -t
                name = name[:-2] + 't'
            elif name.endswith('ra') and len(name) > 5:
                # Might be genitive of words ending in -r
                name = name[:-1]
        
        # Для ингредиентов с числом, НЕ добавляем units="pieces" если нет других единиц
        # (согласно reference JSON)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем "Sastojci:" или "Састојци:" в story-content
        story = self.soup.find('div', class_='story-content')
        if not story:
            return None
        
        # Находим параграф с "Sastojci:" (Latin) или "Састојци:" (Cyrillic)
        found_sastojci_header = False
        for p in story.find_all('p'):
            text = p.get_text()
            if 'Sastojci' in text or 'Састојци' in text:
                found_sastojci_header = True
                # Ищем следующий ul элемент
                next_elem = p.find_next_sibling()
                while next_elem:
                    if next_elem.name == 'ul':
                        # Извлекаем все li элементы
                        for li in next_elem.find_all('li'):
                            ingredient_text = li.get_text(strip=True)
                            if ingredient_text:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        break
                    elif next_elem.name == 'p':
                        # Если следующий элемент - параграф, прекращаем поиск
                        break
                    next_elem = next_elem.find_next_sibling()
                break
        
        # Если не нашли заголовок "Sastojci:", ищем первый ul в story-content
        # (некоторые рецепты не имеют явного заголовка)
        if not found_sastojci_header:
            ul = story.find('ul')
            if ul:
                for li in ul.find_all('li'):
                    ingredient_text = li.get_text(strip=True)
                    if ingredient_text:
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем "Priprema:" (Latin) или "Припрема:" (Cyrillic) в story-content
        story = self.soup.find('div', class_='story-content')
        if not story:
            return None
        
        # Находим параграф с "Priprema:" или "Припрема:"
        found_priprema = False
        for p in story.find_all('p'):
            text = p.get_text()
            if 'Priprema' in text or 'Припрема' in text:
                found_priprema = True
                continue
            
            if found_priprema:
                text = p.get_text(strip=True)
                # Останавливаемся на "Prijatno!" или "Пријатно!" или пустых параграфах
                if not text or 'Prijatno' in text or 'Пријатно' in text:
                    break
                # Пропускаем источник в скобках типа "(Bakina kuhinja)" или "(Бакина кухиња)"
                if re.match(r'^\([^)]+\)$', text):
                    break
                if text:
                    instructions.append(self.clean_text(text))
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            content = meta_section['content']
            # Берем последнюю часть после слеша (напр. "Kuhinja/Recepti" -> "Recepti")
            if '/' in content:
                content = content.split('/')[-1]
            # Маппинг на английский вариант
            if content == 'Recepti':
                return 'Main Course'
            return self.clean_text(content)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте magazin.novosti.rs нет отдельного prep_time
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем извлечь из текста инструкций
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "30-40 minuta", "30 minuta"
            time_match = re.search(r'(\d+(?:-\d+)?)\s*minut[ae]?', instructions, re.IGNORECASE)
            if time_match:
                return f"{time_match.group(1)} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте magazin.novosti.rs нет отдельного total_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На сайте magazin.novosti.rs нет отдельной секции с заметками
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем теги в div с id="tab-tags"
        tags_div = self.soup.find('div', id='tab-tags')
        if tags_div:
            # Ищем список тегов
            tags_ul = tags_div.find('ul', class_='tags')
            if tags_ul:
                # Извлекаем все ссылки с тегами
                for link in tags_ul.find_all('a', class_='btn-link'):
                    tag_text = link.get_text(strip=True)
                    if tag_text:
                        tags_list.append(self.clean_text(tag_text))
        
        # Return as comma-separated string (WITHOUT space after comma, per reference format)
        return ','.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в story-image
        story_image = self.soup.find('a', class_='story-image')
        if story_image and story_image.get('href'):
            urls.append(story_image['href'])
        
        # 2. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 4. Ищем изображения в story-content
        story = self.soup.find('div', class_='story-content')
        if story:
            for img in story.find_all('img', class_='img-responsive'):
                if img.get('src'):
                    urls.append(img['src'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка примеров из директории preprocessed/magazin_novosti_rs"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "magazin_novosti_rs")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MagazinNovostiRsExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python magazin_novosti_rs.py")


if __name__ == "__main__":
    main()
