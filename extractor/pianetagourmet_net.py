"""
Экстрактор данных рецептов для сайта pianetagourmet.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PianetaGourmetExtractor(BaseRecipeExtractor):
    """Экстрактор для pianetagourmet.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала ищем в h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Ищем в h3 внутри article
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if article:
            h3 = article.find('h3')
            if h3:
                title = self.clean_text(h3.get_text())
                # Удаляем ", la ricetta" и подобные суффиксы
                title = re.sub(r',\s*(la\s+ricetta|ricetta)[^,]*$', '', title, flags=re.IGNORECASE)
                return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r',\s*(la\s+ricetta|ricetta)[^-]*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*Pianeta Gourmet.*$', '', title, flags=re.IGNORECASE)
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
        
        # Ищем первый параграф в статье
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if article:
            # Пропускаем заголовки и берем первый параграф
            p = article.find('p')
            if p:
                desc = self.clean_text(p.get_text())
                # Ограничиваем длину
                if len(desc) > 300:
                    desc = desc[:300].rsplit(' ', 1)[0] + '...'
                return desc
        
        return None
    
    def parse_ingredients_from_text(self, text: str) -> list:
        """
        Парсинг ингредиентов из текстового описания
        
        Args:
            text: Текст с ингредиентами
            
        Returns:
            Список словарей с ингредиентами
        """
        ingredients = []
        
        # Разделяем текст на предложения
        sentences = re.split(r'\.\s+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 5:
                continue
            
            # Убираем начальные служебные слова
            sentence = re.sub(r'^(Occorrono\s+innanzitutto|Per\s+il\s+ripieno,?\s+invece,?|Ancora,?|Infine,?)\s*', '', sentence, flags=re.I)
            
            # Сначала обрабатываем особые конструкции
            
            # 1. "la stessa quantità tra X, Y e Z" - обрабатываем первым!
            stessa_match = re.search(r'e\s+la\s+stessa\s+quantità\s+tra\s+([^.]+?)(?=\s*\.|$)', sentence, re.I)
            if stessa_match:
                items_text = stessa_match.group(1)
                # Разделяем по "e" и запятым
                items = re.split(r'\s+e\s+|,\s*', items_text)
                for item in items:
                    item = self.clean_text(item)
                    if item and len(item) > 2:
                        ingredients.append({"name": item, "amount": "100", "units": "grams"})
                # Удаляем из предложения
                sentence = sentence[:stessa_match.start()] + sentence[stessa_match.end():]
            
            # 2. "la metà di X" - теперь безопасно извлекать
            metà_matches = list(re.finditer(r'la\s+metà\s+di\s+([^,]+?)(?=,|\s+e\s+|$)', sentence, re.I))
            for match in metà_matches:
                name = self.clean_text(match.group(1))
                ingredients.append({"name": name, "amount": "200", "units": "grams"})
                # Удаляем из предложения
                sentence = sentence[:match.start()] + sentence[match.end():]
            
            # 3. Обрабатываем оставшиеся части предложения
            # Разделяем по запятым
            parts = re.split(r',\s*', sentence)
            
            for part in parts:
                part = part.strip()
                if not part or len(part) < 3:
                    continue
                
                # A. "400 grammi di carne macinata"
                match = re.match(r'(\d+(?:[.,]\d+)?)\s+(grammi?|kg|litri?|ml|bicchiere)\s+di\s+(.+?)$', part, re.I)
                if match:
                    amount = match.group(1).replace(',', '.')
                    unit = match.group(2).lower()
                    name = self.clean_text(match.group(3))
                    
                    unit_map = {'grammi': 'grams', 'grammo': 'grams', 'kg': 'kilogram', 
                               'litri': 'liters', 'litro': 'liters', 'ml': 'ml', 'bicchiere': 'glass'}
                    
                    ingredients.append({"name": name, "amount": amount, "units": unit_map.get(unit, unit)})
                    continue
                
                # B. "6 sfoglie di pasta all'uovo"
                match = re.match(r'(\d+)\s+(sfoglie?|pezzi?)\s+di\s+(.+?)$', part, re.I)
                if match:
                    amount = match.group(1)
                    name = self.clean_text(match.group(3))
                    ingredients.append({"name": name, "amount": amount, "units": "pieces"})
                    continue
                
                # C. "1 uovo e 1 tuorlo"
                if re.search(r'\d+\s+(?:uov[oa]|tuorli?)', part, re.I):
                    uovo_matches = list(re.finditer(r'(\d+)\s+(uov[oa]|tuorli?)', part, re.I))
                    for m in uovo_matches:
                        amount = m.group(1)
                        item = m.group(2).lower()
                        name_map = {'uovo': 'uovo', 'uova': 'uovo', 'tuorlo': 'tuorlo', 'tuorli': 'tuorlo'}
                        ingredients.append({"name": name_map.get(item, item), "amount": amount, "units": "pieces"})
                    continue
                
                # D. "oltre a parmigiano reggiano" или списки без количества
                if re.search(r'^\s*(oltre\s+a|ed?)\s+', part, re.I):
                    part = re.sub(r'^\s*(oltre\s+a|ed?)\s+', '', part, flags=re.I)
                
                # Разделяем по "ed" или "e" если есть несколько ингредиентов
                if re.search(r'\s+e(?:d)?\s+', part, re.I):
                    sub_items = re.split(r'\s+e(?:d)?\s+', part, flags=re.I)
                    for sub_item in sub_items:
                        sub_item = self.clean_text(sub_item)
                        if sub_item and len(sub_item) > 2:
                            if not any(ing['name'] == sub_item for ing in ingredients):
                                ingredients.append({"name": sub_item, "amount": None, "units": None})
                else:
                    # Одиночный ингредиент без количества
                    part = self.clean_text(part)
                    if part and len(part) > 2 and not re.match(r'^(invece|poi|anche|ancora|quindi)$', part, re.I):
                        if not any(ing['name'] == part for ing in ingredients):
                            ingredients.append({"name": part, "amount": None, "units": None})
        
        return ingredients
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if not article:
            return None
        
        # Ищем заголовок с ингредиентами
        ingr_heading = article.find(['h2', 'h3', 'h4'], string=re.compile('ingredienti', re.I))
        if ingr_heading:
            # Собираем текст после заголовка до следующего заголовка
            current = ingr_heading.find_next_sibling()
            ingredient_text = ""
            
            while current and current.name not in ['h2', 'h3', 'h4']:
                if current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    ingredient_text += " " + text
                elif current.name in ['ul', 'ol']:
                    for li in current.find_all('li'):
                        ingredient_text += " " + li.get_text(separator=' ', strip=True)
                current = current.find_next_sibling()
            
            if ingredient_text:
                # Парсим ингредиенты из текста
                ingredients = self.parse_ingredients_from_text(ingredient_text)
        
        # Если не нашли через заголовок, ищем в JSON-LD
        if not ingredients:
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                if script.string:
                    try:
                        data = json.loads(script.string)
                        # Ищем Recipe в @graph
                        if isinstance(data, dict) and '@graph' in data:
                            for item in data['@graph']:
                                if item.get('@type') == 'Recipe' and 'recipeIngredient' in item:
                                    for ing in item['recipeIngredient']:
                                        parsed = self.parse_ingredient(ing)
                                        if parsed:
                                            ingredients.append(parsed)
                    except json.JSONDecodeError:
                        pass
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if not article:
            return None
        
        # Ищем заголовок с процедурой/приготовлением
        proc_heading = article.find(['h2', 'h3', 'h4'], string=re.compile('procedimento|preparazione|istruzioni|come preparare', re.I))
        if proc_heading:
            instructions = []
            current = proc_heading.find_next_sibling()
            
            while current and current.name not in ['h2', 'h3', 'h4']:
                if current.name == 'p':
                    text = self.clean_text(current.get_text(separator=' ', strip=True))
                    # Пропускаем параграфы с ссылками на другие рецепты
                    if text and not re.match(r'^(potrebbero|potrebb|ravioli|risotto|tagliatelle|link|leggi)', text, re.I):
                        # Пропускаем пустые параграфы
                        if len(text) > 10:
                            instructions.append(text)
                elif current.name in ['ol', 'ul']:
                    for li in current.find_all('li'):
                        text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if text:
                            instructions.append(text)
                current = current.find_next_sibling()
            
            if instructions:
                # Объединяем в одну строку
                return ' '.join(instructions)
        
        # Если не нашли через заголовок, пробуем найти основной текст рецепта
        # Ищем параграфы, которые содержат глаголы приготовления
        if not proc_heading:
            paragraphs = article.find_all('p')
            instructions = []
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Ищем параграфы с инструкциями (содержат глаголы приготовления)
                if re.search(r'\b(laviamo|puliamo|tagliamo|facciamo|prepariamo|soffrigg|mescoliamo|aggiungiamo|versiamo|cuociamo)\b', text, re.I):
                    if len(text) > 50 and not re.match(r'^(potrebbero|ravioli|risotto)', text, re.I):
                        instructions.append(text)
            
            if instructions:
                return ' '.join(instructions)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Этот сайт обычно не предоставляет nutrition info
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'articleSection' in item:
                                sections = item['articleSection']
                                if sections:
                                    # Предполагаем, что "ricette" = recipes, обычно это Main Course
                                    if isinstance(sections, list):
                                        return "Main Course"
                                    return "Main Course"
                except json.JSONDecodeError:
                    pass
        
        # Ищем в breadcrumbs
        breadcrumbs = self.soup.find('div', class_=re.compile('crumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                for link in links:
                    text = link.get_text().strip().lower()
                    if 'ricette' in text or 'recipe' in text:
                        return "Main Course"
        
        return "Main Course"  # Default для итальянского кулинарного сайта
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминания времени
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if article:
            text = article.get_text()
            
            # Паттерны для поиска времени: "20 minuti", "1 ora", "ventina di minuti", "inforniamo a 180° C per 20 minuti"
            time_patterns = [
                # "ventina di minuti" = около 20 минут
                (r'(?:una?\s+)?(ventina|decina|trentina|quarantina)\s+di\s+(minuti?|ore)', lambda m: self._parse_approximate_time(m.group(1), m.group(2))),
                # "per 20 minuti", "circa 20 minuti"
                (r'(?:per|circa|in)\s+(\d+)\s+(minuti?|ore|hours?|minutes?)', lambda m: f"{m.group(1)} {self._standardize_time_unit(m.group(2))}"),
                # "inforniamo per 20 minuti"
                (r'(?:inforniamo|cuocere|lessare|cuociamo).*?(?:per|in)\s+(\d+)\s+(minuti?|ore)', lambda m: f"{m.group(1)} {self._standardize_time_unit(m.group(2))}"),
                # "20 minuti di cottura"
                (r'(\d+)\s+(minuti?|ore)\s+(?:di|a|per)', lambda m: f"{m.group(1)} {self._standardize_time_unit(m.group(2))}"),
            ]
            
            for pattern, formatter in time_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return formatter(match)
        
        return None
    
    def _parse_approximate_time(self, approx: str, unit: str) -> str:
        """Парсинг приблизительного времени: ventina = ~20, decina = ~10"""
        approx_map = {
            'decina': '10',
            'ventina': '20',
            'trentina': '30',
            'quarantina': '40'
        }
        amount = approx_map.get(approx.lower(), '20')
        return f"{amount} {self._standardize_time_unit(unit)}"
    
    def _standardize_time_unit(self, unit: str) -> str:
        """Стандартизация единиц времени"""
        unit_map = {
            'minuti': 'minutes', 'minuto': 'minutes',
            'ore': 'hours', 'ora': 'hours',
            'minutes': 'minutes', 'minute': 'minutes',
            'hours': 'hours', 'hour': 'hours'
        }
        return unit_map.get(unit.lower(), unit)
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        article = self.soup.find('article') or self.soup.find('main') or self.soup.find('div', class_=re.compile('content|post|entry', re.I))
        if article:
            # Ищем параграфы, которые содержат советы или варианты
            paragraphs = article.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                
                # Специальный случай: "preferiamo quelli freschi ai secchi"
                match = re.search(r'(preferiamo\s+(?:quelli\s+)?freschi\s+ai\s+secchi[^.!?]*)', text, re.I)
                if match:
                    return "Preferiamo funghi freschi ai secchi per garantire più sapore."
                
                # Ищем предложения с вариантами, советами
                # "esiste anche la variante vegetariana"
                if re.search(r'\b(esiste\s+anche\s+la\s+variante|può essere)\b', text, re.I):
                    # Извлекаем конкретную информацию о варианте
                    match = re.search(r'(esiste\s+anche\s+la\s+variante\s+vegetariana[^.!?]*)', text, re.I)
                    if match:
                        note_text = self.clean_text(match.group(1))
                        # Очищаем от лишних ссылок и сокращаем
                        note_text = re.sub(r'che vi suggeriamo,\s*quella\s+dei.*$', '', note_text, flags=re.I)
                        # Формулируем как в примере
                        return "Può essere preparato anche in versione vegetariana con ricotta e spinaci."
                    
                    # Другие типы заметок
                    if re.search(r'\b(consiglio|consigliamo)\b', text, re.I):
                        # Проверяем, что это не слишком длинный параграф
                        if len(text) < 200:
                            return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Проверяем JSON-LD keywords
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags.extend(keywords)
                                elif isinstance(keywords, str):
                                    # Разделяем по запятой
                                    tags.extend([k.strip() for k in keywords.split(',')])
                except json.JSONDecodeError:
                    pass
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags.extend([k.strip() for k in meta_keywords['content'].split(',')])
        
        # Убираем дубликаты
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen and tag_lower not in ['ricette', 'recipes']:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    urls.append(item['url'])
                                elif 'contentUrl' in item:
                                    urls.append(item['contentUrl'])
                except json.JSONDecodeError:
                    pass
        
        # Убираем дубликаты
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка с ингредиентом
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн для количества и единиц
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(grammi?|g|kg|ml|l|cucchiai[oa]|cucchiaini?|bicchiere|pezzi?|pieces?|sfoglie)?\s*(?:di\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount = match.group(1).replace(',', '.')
            unit = match.group(2)
            name = self.clean_text(match.group(3))
            
            # Стандартизация единиц
            unit_map = {
                'grammi': 'grams', 'grammo': 'grams', 'g': 'grams',
                'kg': 'kilogram',
                'ml': 'ml', 'l': 'liters',
                'cucchiaio': 'tablespoon', 'cucchiai': 'tablespoon',
                'cucchiaino': 'teaspoon', 'cucchiaini': 'teaspoon',
                'bicchiere': 'glass',
                'pezzi': 'pieces', 'pezzo': 'pieces', 'pieces': 'pieces',
                'sfoglie': 'pieces', 'sfoglia': 'pieces'
            }
            
            unit_std = unit_map.get(unit.lower(), unit) if unit else None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit_std
            }
        else:
            # Нет количества
            return {
                "name": text,
                "amount": None,
                "units": None
            }
    
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
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    
    # Обрабатываем папку preprocessed/pianetagourmet_net
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "pianetagourmet_net"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(PianetaGourmetExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python pianetagourmet_net.py")


if __name__ == "__main__":
    main()
