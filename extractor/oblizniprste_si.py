"""
Экстрактор данных рецептов для сайта oblizniprste.si
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OblizniprsteExtractor(BaseRecipeExtractor):
    """Экстрактор для oblizniprste.si"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='cm-entry-title')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - OblizniPrste.si"
            title = re.sub(r'\s*-\s*OblizniPrste\.si.*$', '', title, flags=re.IGNORECASE)
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
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "šop peteršilja (cca. 10 g)" или "1 strok česna" или "kokosova moka cca. 60 g"
            
        Returns:
            dict: {"name": "šop peteršilja", "amount": 10, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Проверяем различные паттерны
        
        # Паттерн 1: в скобках "(cca. 10 g)"
        paren_match = re.search(r'\((?:cca\.\s*)?(\d+(?:[.,]\d+)?)\s*([a-zA-ZčšžščžČŠŽ]+)\)', text)
        if paren_match:
            amount_str = paren_match.group(1).replace(',', '.')
            try:
                amount_float = float(amount_str)
                amount = int(amount_float) if amount_float == int(amount_float) else amount_float
            except ValueError:
                amount = None
            unit = paren_match.group(2)
            # Удаляем скобки из названия
            name = re.sub(r'\s*\([^)]*\)', '', text).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн 2: в конце "cca. 60 g" или "cca 60 g"
        end_match = re.search(r'^(.+?)\s+(?:cca\.?\s*)?(\d+(?:[.,]\d+)?)\s*([a-zA-ZčšžščžČŠŽ]+)$', text)
        if end_match:
            name = end_match.group(1).strip()
            amount_str = end_match.group(2).replace(',', '.')
            try:
                amount_float = float(amount_str)
                amount = int(amount_float) if amount_float == int(amount_float) else amount_float
            except ValueError:
                amount = None
            unit = end_match.group(3)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн 3: в начале "500 g piškotov" или "200 g mleka"
        start_g_match = re.match(r'^(\d+(?:[.,]\d+)?)\s*([gG]|kg|ml|dL|dl|l)\s+(.+)$', text)
        if start_g_match:
            amount_str = start_g_match.group(1).replace(',', '.')
            try:
                amount_float = float(amount_str)
                amount = int(amount_float) if amount_float == int(amount_float) else amount_float
            except ValueError:
                amount = None
            unit = start_g_match.group(2).lower()
            name = start_g_match.group(3).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн 4: в начале с числом "1 strok česna", "3 jedilne žlice"
        start_num_match = re.match(r'^(\d+(?:[.,/]\d+)?)\s+(.+)$', text)
        if start_num_match:
            amount_str = start_num_match.group(1).replace(',', '.')
            try:
                amount_float = float(amount_str)
                amount = int(amount_float) if amount_float == int(amount_float) else amount_float
            except ValueError:
                amount = None
            name = start_num_match.group(2).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если ничего не совпало, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все заголовки h2, которые содержат "sestavine" (ингредиенты на словенском)
        # или другие ключевые слова, указывающие на ингредиенты
        headings = self.soup.find_all('h2')
        
        ingredient_keywords = ['sestavine', 'za polivko', 'za polnilo', 'za testo']
        
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            
            # Проверяем, содержит ли заголовок ключевые слова ингредиентов
            is_ingredient_section = False
            for keyword in ingredient_keywords:
                # Проверяем наличие ключевого слова
                # Предпочтительно с двоеточием в конце, но не обязательно
                if keyword in heading_text:
                    is_ingredient_section = True
                    break
            
            if is_ingredient_section:
                # Ищем список ингредиентов после этого заголовка
                # Может быть несколько ul/ol списков с подзаголовками h3
                next_sibling = heading.find_next_sibling()
                
                while next_sibling:
                    # Пропускаем h3 (часто это подразделы типа "Čokoladna masa:", "Okrasitev:", "Za testo:")
                    if next_sibling.name == 'h3':
                        next_sibling = next_sibling.find_next_sibling()
                        continue
                    
                    # Если нашли ul или ol список
                    if next_sibling.name in ['ul', 'ol']:
                        items = next_sibling.find_all('li')
                        for item in items:
                            ingredient_text = item.get_text(separator=' ', strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            # Пропускаем заголовки секций
                            if ingredient_text and not ingredient_text.endswith(':'):
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        # НЕ break - продолжаем искать следующие ul списки
                        next_sibling = next_sibling.find_next_sibling()
                    # Если нашли параграф с ингредиентами (некоторые сайты используют p вместо списков)
                    elif next_sibling.name == 'p':
                        # Проверяем, не следующий ли это заголовок
                        if next_sibling.find('strong') or next_sibling.find('h2'):
                            break
                        
                        ingredient_text = next_sibling.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text and not ingredient_text.endswith(':'):
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                        
                        next_sibling = next_sibling.find_next_sibling()
                    # Если нашли другой заголовок h2, останавливаемся для этой секции
                    elif next_sibling.name == 'h2':
                        break
                    else:
                        next_sibling = next_sibling.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем заголовки, которые содержат "– priprava:" или "postopek" (способ приготовления)
        headings = self.soup.find_all('h2')
        
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            
            # Формат может быть:
            # - "Recipe Name – priprava:"
            # - "Postopek za pripravo:"
            # - "Recipe Name – postopek:"
            if ('– priprava:' in heading_text or 
                'priprava:' in heading_text or 
                '– postopek:' in heading_text or 
                'postopek:' in heading_text or
                'postopek za' in heading_text):
                
                # Собираем все параграфы после этого заголовка до следующего заголовка
                next_sibling = heading.find_next_sibling()
                
                while next_sibling:
                    if next_sibling.name == 'p':
                        text = next_sibling.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        
                        # Пропускаем короткие тексты и текст с "uživajte" (это заметки)
                        if text and len(text) > 10 and 'uživajte' not in text.lower():
                            instructions.append(text)
                        
                        next_sibling = next_sibling.find_next_sibling()
                    elif next_sibling.name in ['ol', 'ul']:
                        # Если инструкции в виде списка
                        items = next_sibling.find_all('li')
                        for item in items:
                            text = item.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                instructions.append(text)
                        break
                    elif next_sibling.name in ['h1', 'h2', 'h3']:
                        # Следующий заголовок - останавливаемся
                        break
                    else:
                        next_sibling = next_sibling.find_next_sibling()
                
                if instructions:
                    break
        
        # Объединяем все инструкции в один текст
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Если data - это словарь с @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                return sections[0] if sections else None
                            return sections
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Для oblizniprste.si время не всегда указано явно в HTML
        # Можно попытаться найти в тексте или вернуть None
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после инструкций, которые содержат фразы типа "Uživajte"
        # Это обычно короткие заметки в конце рецепта
        
        # Сначала найдем секцию priprava
        headings = self.soup.find_all('h2')
        priprava_found = False
        
        for heading in headings:
            heading_text = heading.get_text(strip=True).lower()
            
            if '– priprava:' in heading_text or 'priprava:' in heading_text or '– postopek:' in heading_text or 'postopek:' in heading_text:
                priprava_found = True
                next_sibling = heading.find_next_sibling()
                
                # Пропускаем все параграфы с инструкциями
                while next_sibling:
                    if next_sibling.name == 'p':
                        text = next_sibling.get_text(strip=True)
                        text_lower = text.lower()
                        
                        # Проверяем ключевые слова для заметок
                        if 'uživajte' in text_lower:
                            return self.clean_text(text)
                        
                        next_sibling = next_sibling.find_next_sibling()
                    elif next_sibling.name in ['h1', 'h2', 'h3']:
                        break
                    else:
                        next_sibling = next_sibling.find_next_sibling()
                
                break
        
        # Если не нашли в секции priprava, ищем во всех параграфах
        if not priprava_found:
            paragraphs = self.soup.find_all('p')
            
            for p in reversed(paragraphs):
                text = p.get_text(strip=True)
                text_lower = text.lower()
                
                # Проверяем ключевые слова
                if any(keyword in text_lower for keyword in ['uživajte', 'dober tek', 'priporočam', 'nasvet', 'namig']):
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Для oblizniprste.si теги могут быть не указаны явно в HTML
        # Вернем None, если не найдем
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
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
    import os
    # Обрабатываем папку preprocessed/oblizniprste_si
    preprocessed_dir = os.path.join("preprocessed", "oblizniprste_si")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OblizniprsteExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python oblizniprste_si.py")


if __name__ == "__main__":
    main()
