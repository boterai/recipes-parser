"""
Экстрактор данных рецептов для сайта receptfavoriter.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptfavoriterSeExtractor(BaseRecipeExtractor):
    """Экстрактор для receptfavoriter.se"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT10M", "PT1H", или "PT1H10M"
            
        Returns:
            Время в читаемом формате, например "10 minutes", "1 hour", "1 hour 10 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем h1 с itemprop="name"
        h1_tag = self.soup.find('h1', itemprop='name')
        if h1_tag:
            return self.clean_text(h1_tag.get_text())
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из image-caption (короткое описание)
        caption_div = self.soup.find('div', class_='image-caption')
        if caption_div:
            text = self.clean_text(caption_div.get_text())
            # Берем только первое предложение
            if '.' in text:
                text = text.split('.')[0] + '.'
            if text:
                return text
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            text = self.clean_text(meta_desc['content'])
            # Берем только первое предложение
            if '.' in text:
                text = text.split('.')[0] + '.'
            return text
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "400 gram halloumi, 1,5 ostar" или "2 msk smör"
            
        Returns:
            dict: {"name": "halloumi", "amount": 1.5, "units": "ostar"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем запятые на точки в числах (но сохраняем запятые как разделители)
        # Сначала заменяем запятые-разделители на специальный маркер
        # Ищем паттерн "число,число" и заменяем на "число.число"
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        
        # Проверяем, есть ли альтернативная мера после запятой
        # Формат: "400 gram halloumi, 1,5 ostar" -> берем "1,5 ostar" как основную меру
        if ',' in text:
            parts = text.split(',', 1)
            # Проверяем, начинается ли вторая часть с числа
            second_part = parts[1].strip()
            if re.match(r'^[\d\s/.,]+', second_part):
                # Если вторая часть начинается с числа, используем её как меру
                # Извлекаем имя из первой части
                first_part = parts[0].strip()
                # Парсим первую часть для имени - берем последнее слово (название ингредиента)
                # Убираем количество и единицу измерения
                name_pattern = r'(?:[\d\s/.,]+)?\s*(?:[a-zåäöA-ZÅÄÖ]+)?\s+(.+)$'
                name_match = re.search(name_pattern, first_part)
                if name_match:
                    name = name_match.group(1).strip()
                else:
                    # Если не совпало, берем последнее слово
                    words = first_part.split()
                    name = words[-1] if words else first_part
                
                # Парсим вторую часть для количества и единиц
                amount_unit_pattern = r'^([\d\s/.,]+)?\s*([a-zåäöA-ZÅÄÖ]+)?'
                au_match = re.match(amount_unit_pattern, second_part)
                if au_match:
                    amount_str, unit = au_match.groups()
                    amount = None
                    if amount_str:
                        amount_str = amount_str.strip()
                        if '/' in amount_str:
                            parts_frac = amount_str.split()
                            total = 0
                            for part in parts_frac:
                                if '/' in part:
                                    num, denom = part.split('/')
                                    total += float(num) / float(denom)
                                else:
                                    total += float(part)
                            amount = total
                        else:
                            try:
                                amount = float(amount_str.replace(',', '.'))
                            except ValueError:
                                amount = None
                    
                    return {
                        "name": name,
                        "amount": amount,
                        "units": unit if unit else None
                    }
        
        # Стандартный парсинг: количество + единица + название
        pattern = r'^([\d\s/.,]+)?\s*([a-zåäöA-ZÅÄÖ]+)?\s+(.+)$'
        match = re.match(pattern, text)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Обработка дробей типа "1/2"
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
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = None
            
            # Очистка названия - убираем "som", "eller", "gärna" и подобные слова
            if name:
                # Убираем части после "som", "eller", "gärna"
                name = re.split(r'\s+(?:som|eller|gärna)\s+', name)[0]
                # Убираем описания в скобках
                name = re.sub(r'\([^)]*\)', '', name)
                name = name.strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit if unit else None
            }
        
        # Если паттерн не совпал, пробуем только количество + название (без единицы)
        pattern2 = r'^([\d\s/.,]+)?\s+(.+)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            amount_str, name = match2.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
            
            # Очистка названия
            name = re.split(r'\s+(?:som|eller|gärna)\s+', name)[0]
            name = re.sub(r'\([^)]*\)', '', name)
            name = name.strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если ничего не подошло, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все li с itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        for item in ingredient_items:
            ingredient_text = self.clean_text(item.get_text())
            if ingredient_text:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем ol с itemprop="recipeInstructions"
        instructions_ol = self.soup.find('ol', itemprop='recipeInstructions')
        
        if instructions_ol:
            # Находим все li с itemprop="itemListElement"
            step_items = instructions_ol.find_all('li', itemprop='itemListElement')
            
            for item in step_items:
                # Ищем span с itemprop="text"
                text_span = item.find('span', itemprop='text')
                if text_span:
                    step_text = self.clean_text(text_span.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Если нашли шаги, объединяем их через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем span с itemprop="recipeCategory"
        category_span = self.soup.find('span', itemprop='recipeCategory')
        if category_span:
            # Возвращаем английский эквивалент для "Huvudrätter"
            category_text = self.clean_text(category_span.get_text())
            if category_text == "Huvudrätter":
                return "Main Course"
            return category_text
        
        # Альтернативно ищем в хлебных крошках
        breadcrumbs = self.soup.find_all('a', property='item')
        for crumb in breadcrumbs:
            span = crumb.find('span', property='name')
            if span:
                text = self.clean_text(span.get_text())
                if text == "Huvudrätter":
                    return "Main Course"
                elif text:
                    return text
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем meta с itemprop="prepTime"
        prep_meta = self.soup.find('meta', itemprop='prepTime')
        if prep_meta and prep_meta.get('content'):
            return self.parse_iso_duration(prep_meta['content'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем meta с itemprop="cookTime"
        cook_meta = self.soup.find('meta', itemprop='cookTime')
        if cook_meta and cook_meta.get('content'):
            iso_time = cook_meta['content']
            # Преобразуем в минуты для совместимости
            duration = iso_time[2:] if iso_time.startswith('PT') else iso_time
            
            hours = 0
            minutes = 0
            
            hour_match = re.search(r'(\d+)H', duration)
            if hour_match:
                hours = int(hour_match.group(1))
            
            min_match = re.search(r'(\d+)M', duration)
            if min_match:
                minutes = int(min_match.group(1))
            
            # Конвертируем все в минуты
            total_minutes = hours * 60 + minutes
            
            return f"{total_minutes} minutes" if total_minutes > 0 else None
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем meta с itemprop="totalTime"
        total_meta = self.soup.find('meta', itemprop='totalTime')
        if total_meta and total_meta.get('content'):
            return self.parse_iso_duration(total_meta['content'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_parts = []
        
        # Ищем блок с заголовком "Kan förberedas dagen innan" или подобным
        # Ищем все h3 заголовки в теле рецепта
        recipe_body = self.soup.find('div', itemprop='description')
        if recipe_body:
            h3_tags = recipe_body.find_all('h3')
            for h3 in h3_tags:
                heading_text = self.clean_text(h3.get_text())
                # Проверяем, является ли это заголовком для заметок
                if any(keyword in heading_text.lower() for keyword in ['kan förberedas', 'observera', 'notera']):
                    # Добавляем заголовок с точкой
                    notes_parts.append(heading_text + '.')
                    # Собираем следующие параграфы после заголовка
                    next_elem = h3.find_next_sibling()
                    while next_elem and next_elem.name == 'p':
                        p_text = self.clean_text(next_elem.get_text())
                        if p_text:
                            notes_parts.append(p_text)
                        next_elem = next_elem.find_next_sibling()
                elif 'tips' in heading_text.lower():
                    # Для "Tips" не добавляем заголовок, только текст
                    next_elem = h3.find_next_sibling()
                    while next_elem and next_elem.name == 'p':
                        p_text = self.clean_text(next_elem.get_text())
                        if p_text:
                            notes_parts.append(p_text)
                        next_elem = next_elem.find_next_sibling()
        
        if notes_parts:
            return ' '.join(notes_parts)
        
        # Альтернативно ищем по классам
        notes_div = self.soup.find('div', class_='field-name-field-tips')
        if notes_div:
            text = self.clean_text(notes_div.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Берем теги из meta itemprop="keywords"
        keywords_meta = self.soup.find('meta', itemprop='keywords')
        if keywords_meta and keywords_meta.get('content'):
            keywords = keywords_meta['content']
            # Разделяем по запятой и фильтруем
            all_tags = [self.clean_text(tag) for tag in keywords.split(',') if tag.strip()]
            
            # Фильтруем нерелевантные теги (способы приготовления, общие категории)
            exclude_tags = {
                'Fest', 'Vardag', 'Grillat', 'Ugnsrätter', 'Stekt mat', 'Kokt mat',
                'Buffé', 'Kyckling', 'Grönsaker', 'Bönor'
            }
            
            for tag in all_tags:
                if tag not in exclude_tags:
                    # Переводим некоторые теги
                    if tag == "Currygrytor" or tag == "Grytor":
                        if "Curry" not in tags_list and "Grytor" not in tags_list:
                            tags_list.append("Curry" if tag == "Currygrytor" else tag)
                    elif tag == "Vegetarisk":
                        tags_list.append("Vegetarian")
                    elif tag == "Indisk mat":
                        tags_list.append("Indisk")
                    else:
                        tags_list.append(tag)
        
        # Добавляем категорию в теги, если её ещё нет
        category = self.extract_category()
        if category and category not in tags_list:
            tags_list.append(category)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем img с itemprop="image"
        img_tag = self.soup.find('img', itemprop='image')
        if img_tag and img_tag.get('src'):
            urls.append(img_tag['src'])
        
        # 2. Ищем в мета-тегах itemprop="image"
        meta_images = self.soup.find_all('meta', itemprop='image')
        for meta in meta_images:
            if meta.get('content'):
                urls.append(meta['content'])
        
        # 3. Ищем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Делаем URL абсолютными, если они относительные
                if url and not url.startswith('http'):
                    url = 'https://receptfavoriter.se' + url
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
    # Обрабатываем папку preprocessed/receptfavoriter_se
    recipes_dir = os.path.join("preprocessed", "receptfavoriter_se")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReceptfavoriterSeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python receptfavoriter_se.py")


if __name__ == "__main__":
    main()
