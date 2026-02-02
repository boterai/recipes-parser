"""
Экстрактор данных рецептов для сайта cucinagiapponese.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CucinaGiapponeseExtractor(BaseRecipeExtractor):
    """Экстрактор для cucinagiapponese.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        title_elem = self.soup.find('h1', class_='entry-title')
        if title_elem:
            title = title_elem.get_text(strip=True)
            # Формат: "Japanese Name・日本語 – Italian Name" or "Japanese Name・日本語"
            # Предпочитаем итальянское название (после –)
            if '–' in title or '—' in title:
                # Берем часть после длинного тире
                parts = re.split(r'[–—]', title)
                if len(parts) > 1:
                    italian_name = parts[-1].strip()
                    # Убираем японские символы если остались
                    italian_name = re.sub(r'・.*$', '', italian_name)
                    return self.clean_text(italian_name)
            
            # Иначе убираем японские символы после ・
            title = re.sub(r'・.*$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Применяем ту же логику
            if '–' in title or '—' in title:
                parts = re.split(r'[–—]', title)
                if len(parts) > 1:
                    italian_name = parts[-1].strip()
                    italian_name = re.sub(r'・.*$', '', italian_name)
                    # Убираем суффиксы типа "- Ricette..."
                    italian_name = re.sub(r'\s*-\s*Ricette.*$', '', italian_name, flags=re.IGNORECASE)
                    return self.clean_text(italian_name)
            
            title = re.sub(r'・.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Если нет в meta, берем первый параграф
        entry = self.soup.find('div', class_=lambda x: x and 'entry-content' in x if isinstance(x, str) else False)
        if entry:
            paragraphs = entry.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and len(text) > 50:  # Только достаточно длинные параграфы
                    return self.clean_text(text)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном виде"""
        ingredients = []
        
        # Находим entry-content
        entry = self.soup.find('div', class_=lambda x: x and 'entry-content' in x if isinstance(x, str) else False)
        if not entry:
            return None
        
        # Ищем заголовок "Ingredienti"
        ingredients_heading = None
        for h in entry.find_all(['h2', 'h3', 'h4']):
            if 'ingredienti' in h.get_text().lower():
                ingredients_heading = h
                break
        
        # Если нашли заголовок, берем следующий список
        if ingredients_heading:
            ingredient_list = ingredients_heading.find_next(['ul', 'ol'])
            if ingredient_list:
                items = ingredient_list.find_all('li')
                for item in items:
                    # Пытаемся извлечь структурированные данные
                    strong = item.find('strong')
                    if strong:
                        # В <strong> обычно "количество единица ингредиент"
                        strong_text = strong.get_text(strip=True)
                        parsed = self.parse_ingredient(strong_text)
                        if parsed and parsed.get('name'):
                            # Пропускаем мета-информацию
                            name_lower = parsed['name'].lower()
                            if not any(word in name_lower for word in ['varianti', 'tempo', 'difficoltà', 'reperibilità', 'alternativi', 'vegetariana', 'glutine']):
                                ingredients.append(parsed)
                    else:
                        # Если нет strong, пытаемся парсить весь текст
                        text = item.get_text(strip=True)
                        if text and not text.lower().startswith('varianti'):
                            parsed = self.parse_ingredient(text)
                            if parsed and parsed.get('name'):
                                name_lower = parsed['name'].lower()
                                if not any(word in name_lower for word in ['varianti', 'tempo', 'difficoltà', 'reperibilità', 'alternativi', 'vegetariana', 'glutine']):
                                    ingredients.append(parsed)
        else:
            # Если заголовка нет, используем второй список
            lists = entry.find_all(['ul', 'ol'])
            if len(lists) > 1:
                ingredient_list = lists[1]
                items = ingredient_list.find_all('li')
                for item in items:
                    strong = item.find('strong')
                    if strong:
                        strong_text = strong.get_text(strip=True)
                        parsed = self.parse_ingredient(strong_text)
                        if parsed and parsed.get('name'):
                            name_lower = parsed['name'].lower()
                            if not any(word in name_lower for word in ['varianti', 'tempo', 'difficoltà', 'reperibilità', 'alternativi', 'vegetariana', 'glutine']):
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "300g di cavolo" или "2 uova"
            
        Returns:
            dict: {"name": "cavolo", "amount": "300", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Убираем текст после скобок (описание)
        # Пример: "300g di cavolo(la ricetta originale..." -> "300g di cavolo"
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Убираем текст после точки (дополнительные пояснения)
        text = re.sub(r'\..*$', '', text)
        
        # Убираем "di" и другие предлоги в начале
        text = re.sub(r'^di\s+', '', text)
        
        # Исправляем слитые слова типа "dipolpa" -> "di polpa", "buonasalsa" -> "buona salsa"
        text = re.sub(r'di([a-z])', r'di \1', text)
        text = re.sub(r'buona([a-z])', r'buona \1', text)
        text = re.sub(r'buono([a-z])', r'buono \1', text)
        
        # Паттерн для итальянских ингредиентов: "300g di cavolo", "2 uova", "un cucchiaio di..."
        # Ищем количество, единицу и название
        pattern = r'^(\d+(?:[.,]\d+)?)\s*([a-z]+)?\s*(?:di\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Нормализуем количество - преобразуем в число
            try:
                amount = int(amount_str.replace(',', '.').split('.')[0]) if amount_str else None
            except:
                amount = amount_str.replace(',', '.') if amount_str else None
            
            # Проверяем, является ли unit действительно единицей измерения
            valid_units = ['g', 'gr', 'grammi', 'kg', 'ml', 'l', 'litri', 'cucchiaio', 'cucchiai', 'cucchiaia', 
                          'cucchiaino', 'cucchiaini', 'fette', 'fetta', 'pezzi', 'pezzo', 'pizzico', 'spicchio', 'spicchi']
            
            if unit and unit.lower() not in valid_units:
                # unit это не единица, а часть названия
                name = unit + ' ' + name if name else unit
                unit = None
            
            # Нормализуем единицу измерения
            if unit:
                unit = unit.strip()
                # Сокращаем длинные формы
                unit_map = {
                    'grammi': 'g',
                    'litri': 'l',
                    'cucchiaio': 'cucchiaio',
                    'cucchiai': 'cucchiaio',
                    'cucchiaia': 'cucchiaio',
                    'cucchiaini': 'cucchiaino',
                    'fetta': 'fette',
                    'fette': 'fette',
                    'spicchi': 'spicchio'
                }
                unit = unit_map.get(unit, unit)
            
            # Очищаем название
            name = name.strip()
            # Убираем артикли и прилагательные
            name = re.sub(r'^(il|la|lo|i|gli|le|un|una|uno|del|della|dello|dei|degli|delle|buona|buono)\s+', '', name)
            # Убираем предлоги
            name = re.sub(r'^(di|per|a)\s+', '', name)
            # Убираем апострофы в начале (d'aglio -> aglio)
            name = re.sub(r"^d'", '', name)
            # Убираем текст после двоеточия или "per la" (для гарнира и т.п.)
            name = re.sub(r':.*$', '', name)
            name = re.sub(r'\s+per\s+(la|il|i|le)\s+.*$', '', name)
            name = name.strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "amount": amount,
                    "units": unit if unit else None
                }
        
        # Если не совпал паттерн с числом, проверяем текстовое количество
        # "Un cucchiaio di...", "Due uova", etc
        text_amount_pattern = r'^(un[oa]?|due|tre|quattro|cinque)\s+(cucchiai[oa]?|cucchiaino?|fette?|pizzico|spicchio|uov[aeio])\s*(?:di\s+)?(.+)?'
        match = re.match(text_amount_pattern, text, re.IGNORECASE)
        
        if match:
            amount_word, unit, name = match.groups()
            
            # Конвертируем текстовые числа
            amount_map = {
                'un': 1, 'una': 1, 'uno': 1,
                'due': 2, 'tre': 3, 'quattro': 4, 'cinque': 5
            }
            amount = amount_map.get(amount_word.lower(), 1)
            
            # Проверяем, не является ли единица самим ингредиентом (напр. "2 uova")
            if unit.lower().startswith('uov'):
                # "uova" - это сам ингредиент
                return {
                    "name": "uova",
                    "amount": amount,
                    "units": None
                }
            
            # Нормализуем единицу
            unit_map = {
                'cucchiaio': 'cucchiaio',
                'cucchiai': 'cucchiaio',
                'cucchiaia': 'cucchiaio',
                'cucchiaino': 'cucchiaino',
                'cucchiaini': 'cucchiaino',
                'fetta': 'fette',
                'fette': 'fette',
                'spicchi': 'spicchio'
            }
            unit = unit_map.get(unit.lower(), unit)
            
            # Очищаем название
            if name:
                name = name.strip()
                name = re.sub(r'^(il|la|lo|i|gli|le|di|del|della|buona|buono)\s+', '', name)
                name = re.sub(r"^d'", '', name)
                name = re.sub(r':.*$', '', name)
                name = name.strip()
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "amount": amount,
                    "units": unit
                }
            elif not name and unit != 'uova':
                # Если нет названия, но есть количество и единица - возвращаем None
                # (это неполный ингредиент)
                return None
        
        # Проверяем простые паттерны типа "2 uova"
        simple_pattern = r'^(\d+)\s+(.+)'
        match = re.match(simple_pattern, text, re.IGNORECASE)
        if match:
            amount_str, name = match.groups()
            name = name.strip()
            name = re.sub(r':.*$', '', name)
            name = re.sub(r'^(di|per|a)\s+', '', name)
            name = re.sub(r"^d'", '', name)
            
            try:
                amount = int(amount_str)
            except:
                amount = amount_str
            
            if name and len(name) > 1:
                return {
                    "name": name,
                    "amount": amount,
                    "units": None
                }
        
        # Если совсем не распарсилось, возвращаем как ингредиент без количества
        # но только если это не служебный текст
        name = text.strip()
        name = re.sub(r'^(di|per|a)\s+', '', name)
        name = re.sub(r"^d'", '', name)
        name = re.sub(r':.*$', '', name)
        name = re.sub(r'\s+per\s+(la|il|i|le)\s+.*$', '', name)
        name = name.strip()
        
        # Пропускаем служебные тексты
        if name and len(name) > 2 and not any(word in name for word in ['varianti', 'guarnizione', 'piacere']):
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        entry = self.soup.find('div', class_=lambda x: x and 'entry-content' in x if isinstance(x, str) else False)
        if not entry:
            return None
        
        # Ищем заголовок "Preparazione" или подобный
        prep_heading = None
        for h in entry.find_all(['h2', 'h3', 'h4']):
            if 'preparazione' in h.get_text().lower() or 'cottura' in h.get_text().lower():
                prep_heading = h
                break
        
        if prep_heading:
            # Собираем все списки после заголовка "Preparazione"
            current = prep_heading.find_next_sibling()
            while current:
                if current.name in ['h2', 'h3']:
                    # Остановимся на следующем заголовке
                    break
                
                if current.name in ['ol', 'ul']:
                    # Это список с шагами
                    items = current.find_all('li')
                    for item in items:
                        text = item.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            steps.append(text)
                elif current.name == 'p':
                    # Или параграф с инструкцией
                    text = current.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text and len(text) > 20:  # Только значимые тексты
                        steps.append(text)
                
                current = current.find_next_sibling()
        
        # Если не нашли по заголовку, ищем списки с инструкциями
        if not steps:
            lists = entry.find_all(['ol', 'ul'])
            # Ищем список, который не является списком ингредиентов
            # (список инструкций обычно не имеет <strong> в начале)
            for lst in lists:
                items = lst.find_all('li')
                if len(items) > 2:
                    # Проверяем, что это не список ингредиентов
                    strong_count = sum(1 for item in items if item.find('strong'))
                    if strong_count < len(items) * 0.3:  # Мало strong тегов
                        for item in items:
                            text = item.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                steps.append(text)
                        if steps:
                            break
        
        # Нумеруем шаги, если они ещё не пронумерованы
        if steps:
            formatted_steps = []
            for i, step in enumerate(steps, 1):
                if not re.match(r'^\d+\.', step):
                    formatted_steps.append(f"{i}. {step}")
                else:
                    formatted_steps.append(step)
            return ' '.join(formatted_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Возвращаем фиксированную категорию для основных блюд
        # На cucinagiapponese.net рецепты обычно являются основными блюдами
        return "Main Course"
    
    def extract_time_from_meta_list(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из первого списка с мета-информацией
        
        Args:
            time_type: 'prep' или 'cook' или 'total'
        """
        entry = self.soup.find('div', class_=lambda x: x and 'entry-content' in x if isinstance(x, str) else False)
        if not entry:
            return None
        
        lists = entry.find_all(['ul', 'ol'])
        if not lists:
            return None
        
        # Первый список обычно содержит мета-информацию
        first_list = lists[0]
        items = first_list.find_all('li')
        
        for item in items:
            text = item.get_text(strip=True)
            
            # Ищем "Tempo di preparazione: XX'" или подобное
            if 'tempo' in text.lower() and 'preparazione' in text.lower():
                # Извлекаем время
                time_match = re.search(r'(\d+)\s*[′\']', text)
                if time_match:
                    minutes = time_match.group(1)
                    return f"{minutes} minutes"
                
                # Или в формате "XX minuti"
                time_match = re.search(r'(\d+)\s*minut', text, re.IGNORECASE)
                if time_match:
                    minutes = time_match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_meta_list('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На этом сайте обычно указано только общее время подготовки
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Используем то же время, что и prep_time, т.к. на сайте это общее время
        return self.extract_time_from_meta_list('prep')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        entry = self.soup.find('div', class_=lambda x: x and 'entry-content' in x if isinstance(x, str) else False)
        if not entry:
            return None
        
        # Ищем секции "Abbinamenti", "Note", или подобные
        for h in entry.find_all(['h2', 'h3', 'h4']):
            heading_text = h.get_text().lower()
            if any(keyword in heading_text for keyword in ['abbinamenti', 'note', 'consigli', 'varianti']):
                # Собираем текст после этого заголовка
                current = h.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3']:
                        break
                    
                    if current.name == 'p':
                        text = current.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text and len(text) > 20:
                            notes.append(text)
                    
                    current = current.find_next_sibling()
        
        # Также проверяем список ингредиентов на наличие "Varianti"
        lists = entry.find_all(['ul', 'ol'])
        for lst in lists:
            items = lst.find_all('li')
            for item in items:
                strong = item.find('strong')
                if strong and 'varianti' in strong.get_text().lower():
                    text = item.get_text(strip=True)
                    # Убираем "Varianti:" из начала
                    text = re.sub(r'^Varianti:\s*', '', text, flags=re.IGNORECASE)
                    text = self.clean_text(text)
                    if text:
                        notes.append(text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в мета-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Также можем извлечь из article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag_meta in article_tags:
            if tag_meta.get('content'):
                tags.append(tag_meta['content'].strip())
        
        # Убираем дубликаты
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # Убираем дубликаты
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls)
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/cucinagiapponese_net
    recipes_dir = os.path.join("preprocessed", "cucinagiapponese_net")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CucinaGiapponeseExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cucinagiapponese_net.py")


if __name__ == "__main__":
    main()
