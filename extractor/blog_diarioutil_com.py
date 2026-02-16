"""
Экстрактор данных рецептов для сайта blog.diarioutil.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BlogDiarioutilExtractor(BaseRecipeExtractor):
    """Экстрактор для blog.diarioutil.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы типа " - Diario Util - Blog"
            title_text = re.sub(r'\s+-\s+Diario Util.*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем заголовок "Ingredienti" / "Ingredientes"
        content_div = self.soup.find('div', itemprop='articleBody')
        if not content_div:
            return None
        
        # Находим все заголовки h3
        for h3 in content_div.find_all(['h3', 'h2']):
            h3_text = h3.get_text().strip().lower()
            
            # Проверяем, является ли это заголовком ингредиентов
            if 'ingredient' in h3_text or 'ingrediente' in h3_text:
                # Ищем следующий ul после заголовка
                next_sibling = h3.find_next_sibling()
                while next_sibling:
                    if next_sibling.name == 'ul' and 'wp-block-list' in next_sibling.get('class', []):
                        # Извлекаем ингредиенты из списка
                        for li in next_sibling.find_all('li'):
                            ingredient_text = self.clean_text(li.get_text())
                            if ingredient_text:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        break
                    # Если натыкаемся на другой заголовок, останавливаемся
                    if next_sibling.name in ['h2', 'h3', 'h4']:
                        break
                    next_sibling = next_sibling.find_next_sibling()
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 g di pasta" или "1 tazza di yogurt"
            
        Returns:
            dict: {"name": "pasta", "amount": "250", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Обработка фраз типа "1 cucchiaio e mezzo" (1 ложка с половиной) -> "1.5 cucchiai"
        # Важно: делаем это ДО разбиения на части
        text = re.sub(r'(\d+)\s+cucchiaio\s+e\s+mezzo\b', lambda m: f"{float(m.group(1)) + 0.5} cucchiai", text)
        text = re.sub(r'(\d+)\s+cucchiaino\s+e\s+mezzo\b', lambda m: f"{float(m.group(1)) + 0.5} cucchiaini", text)
        text = re.sub(r'(\d+)\s+tazza\s+e\s+mezzo\b', lambda m: f"{float(m.group(1)) + 0.5} tazze", text)
        text = re.sub(r'(\d+)\s+(\w+)\s+e\s+un\s+quarto\b', lambda m: f"{float(m.group(1)) + 0.25} {m.group(2)}", text)
        text = re.sub(r'(\d+)\s+(\w+)\s+e\s+tre\s+quarti\b', lambda m: f"{float(m.group(1)) + 0.75} {m.group(2)}", text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживаем различные форматы: "250 g di pasta", "1 tazza di yogurt", "3 cucchiai di cocco"
        pattern = r'^([\d\s/.,]+)?\s*(g|gr|kg|ml|l|litro|litri|tazza|tazze|cucchiai|cucchiaio|cucchiaini|cucchiaino|pizzico|spicchio|spicchi|fetta|fette|foglia|foglie|rametto|rametti|confezione|confezioni|lattina|lattine|barattolo|barattoli)?\s*(?:di|da|circa)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                amount = float(amount_str.replace(',', '.'))
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "a piacere", "qb", "opzionale", "per guarnire"
        name = re.sub(r'\b(a piacere|qb|q\.?b\.?|opzionale|per guarnire|facoltativo)\b', '', name, flags=re.IGNORECASE)
        # Убираем артикли и предлоги в начале: "di ", "d'", "o di ", "o "
        name = re.sub(r'^(di\s+|d\'|o\s+di\s+|o\s+)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем заголовок "Come preparare" / "Preparazione" / "Modo di preparare"
        content_div = self.soup.find('div', itemprop='articleBody')
        if not content_div:
            return None
        
        # Находим все заголовки h2 и h3
        for header in content_div.find_all(['h2', 'h3']):
            header_text = header.get_text().strip().lower()
            
            # Проверяем, является ли это заголовком инструкций
            if any(keyword in header_text for keyword in ['come preparare', 'preparazione', 'modo di preparare', 'istruzioni']):
                # Ищем следующий ol или ul после заголовка
                next_sibling = header.find_next_sibling()
                while next_sibling:
                    if next_sibling.name == 'ol' and 'wp-block-list' in next_sibling.get('class', []):
                        # Извлекаем шаги из упорядоченного списка
                        for li in next_sibling.find_all('li'):
                            step_text = self.clean_text(li.get_text())
                            if step_text:
                                instructions.append(step_text)
                        break
                    # Если натыкаемся на другой заголовок, останавливаемся
                    if next_sibling.name in ['h2', 'h3', 'h4']:
                        break
                    next_sibling = next_sibling.find_next_sibling()
                
                if instructions:
                    break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем articleSection в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из хлебных крошек
        breadcrumb = self.soup.find('nav', attrs={'aria-label': 'Breadcrumbs'})
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Берем предпоследнюю ссылку (последняя обычно - сам рецепт)
            if len(links) >= 2:
                category_link = links[-1]  # или links[1] если начинаем с "Home"
                return self.clean_text(category_link.get_text())
        
        return None
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_label: Метка времени для поиска ('prep', 'cook', 'total')
        """
        # Ищем в тексте статьи упоминания времени
        content_div = self.soup.find('div', itemprop='articleBody')
        if not content_div:
            return None
        
        text = content_div.get_text()
        
        # Паттерны поиска в зависимости от типа времени
        time_patterns = {
            'prep': [
                r'(?:ci vogliono|richiede|prepararlo in)\s+(?:meno di\s+)?(\d+)\s+minut',
                r'tempo\s+di\s+preparazione[:\s]+(\d+)\s+minut', 
                r'preparazione[:\s]+(\d+)\s+minut',
                r'tempo\s+prep[:\s]+(\d+)\s+minut'
            ],
            'cook': [
                r'tempo\s+di\s+cottura[:\s]+(\d+)\s+minut', 
                r'cottura[:\s]+(\d+)\s+minut',
                r'tempo\s+cook[:\s]+(\d+)\s+minut',
                r'cuocere\s+per\s+(\d+)\s+minut'
            ],
            'total': [
                r'lasciare\s+riposare.*?(?:almeno|per)\s+(\d+)\s+minut',
                r'tempo\s+totale[:\s]+(\d+)\s+minut', 
                r'totale[:\s]+(\d+)\s+minut'
            ]
        }
        
        patterns = time_patterns.get(time_label, [])
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        content_div = self.soup.find('div', itemprop='articleBody')
        if not content_div:
            return None
        
        # Ищем заголовки с советами/заметками
        for header in content_div.find_all(['h2', 'h3']):
            header_text = header.get_text().strip().lower()
            
            # Проверяем, является ли это заголовком советов
            if any(keyword in header_text for keyword in ['consigli', 'note', 'varianti', 'suggerimenti', 'tip']):
                # Собираем текст после заголовка до следующего заголовка
                next_sibling = header.find_next_sibling()
                while next_sibling:
                    if next_sibling.name in ['h2', 'h3', 'h4']:
                        break
                    
                    if next_sibling.name == 'p':
                        text = self.clean_text(next_sibling.get_text())
                        if text:
                            notes.append(text)
                    elif next_sibling.name == 'ul':
                        for li in next_sibling.find_all('li'):
                            text = self.clean_text(li.get_text())
                            if text:
                                notes.append(text)
                    
                    next_sibling = next_sibling.find_next_sibling()
                
                if notes:
                    break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем keywords в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                return ', '.join(keywords)
                            elif isinstance(keywords, str):
                                return keywords
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем image в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Article с thumbnailUrl
                        elif item.get('@type') == 'Article' and 'thumbnailUrl' in item:
                            urls.append(item['thumbnailUrl'])
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/blog_diarioutil_com
    preprocessed_dir = os.path.join("preprocessed", "blog_diarioutil_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BlogDiarioutilExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python blog_diarioutil_com.py")


if __name__ == "__main__":
    main()
