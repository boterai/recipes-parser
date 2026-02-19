"""
Экстрактор данных рецептов для сайта crockpot-romania.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CrockpotRomaniaExtractor(BaseRecipeExtractor):
    """Экстрактор для crockpot-romania.ro"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT7H20M"
            
        Returns:
            Время в формате "7h 20m" или "20 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        if not duration:  # Пустое значение после PT
            return None
        
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 с itemprop="name"
        h1 = self.soup.find('h1', itemprop='name')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем "by Автор" из названия
            name = re.sub(r'\s+by\s+.*$', '', name, flags=re.IGNORECASE)
            # Убираем "Rețetă" / "Reteta" в начале
            name = re.sub(r'^Rețetă\s+', '', name, flags=re.IGNORECASE)
            name = re.sub(r'^Reteta\s+', '', name, flags=re.IGNORECASE)
            # Убираем текст после "la Slow Cooker", "la slow cooker", "gătită lent"
            name = re.sub(r'\s+(la\s+slow\s*cooker|gătită\s+lent|la\s+crock[-\s]*pot).*$', '', name, flags=re.IGNORECASE)
            # Убираем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
            # Делаем lowercase
            return name.lower() if name else None
        
        # Альтернативно - из мета-тега
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Применяем те же преобразования
            title = re.sub(r'\s+by\s+.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Rețetă\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Reteta\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+(la\s+slow\s*cooker|gătită\s+lent|la\s+crock[-\s]*pot).*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+', ' ', title).strip()
            return title.lower() if title else None
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в div с itemprop="description"
        desc_div = self.soup.find('div', itemprop='description')
        if desc_div:
            desc_text = self.clean_text(desc_div.get_text())
            # Разбиваем по предложениям
            if desc_text:
                # Разделяем по точке, вопросительному и восклицательному знаку
                sentences = re.split(r'([.!?])\s+', desc_text)
                # Собираем обратно с пунктуацией
                full_sentences = []
                i = 0
                while i < len(sentences):
                    if i + 1 < len(sentences) and sentences[i+1] in '.!?':
                        full_sentences.append(sentences[i] + sentences[i+1])
                        i += 2
                    else:
                        if sentences[i].strip():
                            full_sentences.append(sentences[i])
                        i += 1
                
                # Фильтруем предложения
                valid_sentences = []
                for sent in full_sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    # Пропускаем вопросы
                    if sent.endswith('?'):
                        continue
                    # Пропускаем предложения, начинающиеся с "Uneori" или других вводных слов
                    if sent.lower().startswith('uneori,'):
                        continue
                    valid_sentences.append(sent)
                
                # Возвращаем первые 1-2 предложения
                if valid_sentences:
                    if len(valid_sentences) >= 2:
                        # Проверяем общую длину - если 2 предложения слишком длинные, берем 1
                        combined = ' '.join(valid_sentences[:2])
                        if len(combined) > 200:
                            return valid_sentences[0]
                        return combined
                    return valid_sentences[0]
        
        # Альтернативно - из мета description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1kg carne de găină" или "150g țelină"
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "unit": None}
        
        text = self.clean_text(ingredient_text)
        
        # Сначала извлекаем unit из конструкций "după gust", "după preferință"
        unit_after = None
        match_after_unit = re.search(r',?\s+(după\s+(?:gust|preferință))$', text, re.IGNORECASE)
        if match_after_unit:
            unit_after = match_after_unit.group(1).strip()
            # Удаляем это из текста
            text = text[:match_after_unit.start()].strip()
        
        # Удаляем текст в скобках из названия, но сохраняем для извлечения количества/единицы
        cleaned_text = re.sub(r'\s*\([^)]*\)', '', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1kg carne", "150g țelină", "2 lingurițe de sare", "1 ceapă mare"
        # Поддерживаем: числа с точкой/дробью/дефисом, единицы измерения, остальное - название
        # ВАЖНО: более длинные единицы должны быть ПЕРЕД короткими (lingurițe перед l)
        pattern = r'^([\d\s/.,\-]+)?\s*(linguri[țt]?[eă]?[s]?|lingur[iă]|tablespoons?|teaspoons?|kilograms?|milliliters?|pounds?|ounces?|grams?|liters?|cloves?|tbsp|tsp|cups?|lbs?|kg|ml|oz|g|l|medium|large|small)?\s*(?:de\s+)?(.+)?$'
        
        match = re.match(pattern, cleaned_text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем всё как название
            return {
                "name": cleaned_text,
                "amount": None,
                "unit": unit_after
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или диапазонов "2.5-3" или "2,5-3"
            amount = amount_str.replace(',', '.')  # Нормализуем запятые в точки
        
        # Обработка единицы измерения
        # Если нашли unit_after (например, "după gust"), используем его
        if unit_after:
            unit = unit_after
        elif unit:
            unit = unit.strip()
        
        # Очистка названия
        if name:
            name = name.strip()
            # Удаляем "de" в начале (например, "de sare" -> "sare")
            name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE)
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name if name else None,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Метод 1: Извлекаем из meta tags с itemprop="recipeIngredient"
        meta_ingredients = self.soup.find_all('meta', itemprop='recipeIngredient')
        
        if meta_ingredients:
            for meta in meta_ingredients:
                content = meta.get('content')
                if content:
                    parsed = self.parse_ingredient_text(content)
                    ingredients_list.append({
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    })
        
        # Метод 2: Если нет meta тегов, пробуем извлечь из span с itemprop="ingredients"
        if not ingredients_list:
            span_ingredients = self.soup.find_all('span', itemprop='ingredients')
            for span in span_ingredients:
                text = span.get_text()
                if text:
                    parsed = self.parse_ingredient_text(text)
                    ingredients_list.append({
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    })
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Сначала пробуем извлечь из div после "Mod de preparare"
        # Ищем h2 с текстом "Mod de preparare" и берем следующий div
        headers = self.soup.find_all('h2')
        for header in headers:
            if 'mod de preparare' in header.get_text().lower():
                # Берем следующий div с классом recipe-description
                next_div = header.find_next_sibling('div', class_='recipe-description')
                if next_div:
                    # Извлекаем текст, удаляя теги <b> но сохраняя их содержимое
                    # Заменяем <br> на пробелы
                    text = next_div.get_text(separator=' ', strip=True)
                    # Очищаем множественные пробелы
                    text = re.sub(r'\s+', ' ', text)
                    # Заменяем " Pasul N. " на " Pasul N: "
                    text = re.sub(r'Pasul\s+(\d+)\s*\.', r'Pasul \1:', text)
                    return self.clean_text(text) if text else None
        
        # Если не нашли выше, пробуем meta tag (но там без диакритиков)
        meta_instructions = self.soup.find('meta', itemprop='recipeInstructions')
        if meta_instructions and meta_instructions.get('content'):
            instructions = meta_instructions['content']
            # Заменяем точки после номеров шагов на двоеточия
            instructions = re.sub(r'Pasul\s+(\d+)\.', r'Pasul \1:', instructions)
            return self.clean_text(instructions)
        
        # Альтернативно - ищем div с классом "mod-preparare"
        instructions_div = self.soup.find('div', class_='mod-preparare')
        if instructions_div:
            # Извлекаем все параграфы или li элементы
            steps = []
            paragraphs = instructions_div.find_all(['p', 'li'])
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                if text:
                    steps.append(text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Маппинг румынских категорий на английские
        category_mapping = {
            'carne': 'Main Course',
            'pește': 'Main Course',
            'pesti': 'Main Course',
            'supe și ciorbe': 'Supe și ciorbe',
            'supe si ciorbe': 'Supe și ciorbe',
            'deserturi': 'Dessert',
            'salate': 'Salads',
        }
        
        # Ищем в breadcrumbs - берем предпоследнюю ссылку (перед самим рецептом)
        breadcrumbs = self.soup.find('div', class_='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Пропускаем первую ссылку (home) и последнюю (сам рецепт), берем предпоследнюю
            if len(links) >= 3:
                # links[0] = home, links[1] = retete, links[2] = category, links[3] = recipe
                # Берем links[-2] (предпоследний) - это должна быть категория
                category_link = links[-2] if len(links) > 2 else links[-1]
                text = self.clean_text(category_link.get_text())
                if text and text.lower() not in ['home', 'retete culinare', 'retete']:
                    # Проверяем маппинг
                    text_lower = text.lower()
                    return category_mapping.get(text_lower, text)
        
        # Если не нашли в breadcrumbs, пробуем meta tag
        meta_category = self.soup.find('meta', itemprop='recipeCategory')
        if meta_category and meta_category.get('content'):
            text = self.clean_text(meta_category['content'])
            text_lower = text.lower()
            return category_mapping.get(text_lower, text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала проверяем prepTime
        meta_prep = self.soup.find('meta', itemprop='prepTime')
        if meta_prep and meta_prep.get('content'):
            return self.parse_iso_duration(meta_prep['content'])
        
        # Если нет prepTime, но есть totalTime и нет cookTime - используем totalTime
        meta_cook = self.soup.find('meta', itemprop='cookTime')
        cook_content = meta_cook.get('content') if meta_cook else None
        
        # Если cookTime пустой или отсутствует, используем totalTime как prep_time
        if not cook_content or cook_content == 'PT':
            meta_total = self.soup.find('meta', itemprop='totalTime')
            if meta_total and meta_total.get('content'):
                total_duration = self.parse_iso_duration(meta_total['content'])
                if total_duration:
                    return total_duration
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        meta_cook = self.soup.find('meta', itemprop='cookTime')
        if meta_cook and meta_cook.get('content'):
            return self.parse_iso_duration(meta_cook['content'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте totalTime обычно используется как prep_time или cook_time
        # Возвращаем None, так как время уже извлечено в соответствующие поля
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На crockpot-romania.ro заметки обычно не выделены отдельно
        # Проверяем возможные варианты
        notes_selectors = [
            ('div', {'class': re.compile(r'note', re.I)}),
            ('div', {'class': re.compile(r'tips', re.I)}),
            ('div', {'class': re.compile(r'sfat', re.I)}),
        ]
        
        for tag, attrs in notes_selectors:
            notes = self.soup.find(tag, attrs)
            if notes:
                text = self.clean_text(notes.get_text())
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Очищаем и форматируем
            tags = [self.clean_text(tag) for tag in keywords.split(',')]
            tags = [tag for tag in tags if tag]
            return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем img с itemprop="image"
        img_with_itemprop = self.soup.find('img', itemprop='image')
        if img_with_itemprop and img_with_itemprop.get('src'):
            src = img_with_itemprop['src']
            # Конвертируем относительный URL в абсолютный
            if src.startswith('/'):
                src = 'https://www.crockpot-romania.ro' + src
            urls.append(src)
        
        # 2. Ищем в мета-тегах og:image
        og_images = self.soup.find_all('meta', property='og:image')
        for og_img in og_images:
            if og_img.get('content'):
                urls.append(og_img['content'])
        
        # 3. Ищем в мета-тегах twitter:image
        twitter_image = self.soup.find('meta', property='twitter:image')
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
        # Извлекаем все поля
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        # Возвращаем словарь со всеми полями
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Обработка директории с HTML файлами"""
    import os
    
    # Обрабатываем директорию preprocessed/crockpot-romania_ro
    preprocessed_dir = os.path.join("preprocessed", "crockpot-romania_ro")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CrockpotRomaniaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python crockpot-romania_ro.py")


if __name__ == "__main__":
    main()
