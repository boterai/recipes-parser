"""
Экстрактор данных рецептов для сайта hellotaste.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HellotasteRoExtractor(BaseRecipeExtractor):
    """Экстрактор для hellotaste.ro"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 внутри article.articol
        article = self.soup.find('article', class_='articol')
        if article:
            h1 = article.find('h1')
            if h1:
                title = self.clean_text(h1.get_text())
                # Удаляем подзаголовок после точки (например, "Название. Подзаголовок" -> "Название")
                title = re.sub(r'\.\s+.*$', '', title)
                return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - HelloTaste.ro"
            title = re.sub(r'\s*-\s*HelloTaste\.ro.*$', '', title, flags=re.IGNORECASE)
            # Удаляем подзаголовок после точки
            title = re.sub(r'\.\s+.*$', '', title)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find('div', class_='wp-block-digitalag-ingrediente')
        
        if not ingredients_container:
            return None
        
        # Находим все списки ингредиентов
        lists = ingredients_container.find_all('ul')
        
        for ul in lists:
            items = ul.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g făină albă" или "1 linguriță extract de vanilie"
            
        Returns:
            dict: {"name": "făină albă", "amount": 500, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Важно: более длинные единицы должны идти первыми, чтобы "linguriță" не совпадал с "l"
        # Примеры: "500 g făină albă", "1 linguriță extract de vanilie", "sare"
        pattern = r'^([\d\s/.,]+)?\s*(lingurit[ăeș]+|lingur[ăiș]+|kilograme?|mililitr[ui]?|gram[eș]?|litr[ui]?|plic(?:ul)?|pac(?:het)?|can(?:ul)?|buc(?:ăț[iă])?|felii?|căpățân[ăi]|praf|conserv[ăe]|kg|ml|un\s+praf|pentru\s+\w+|g|l)?\s*(.+)'
        
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
                amount = int(total) if total == int(total) else total
            else:
                cleaned_amount = amount_str.replace(',', '.')
                try:
                    amount = int(cleaned_amount) if float(cleaned_amount) == int(float(cleaned_amount)) else float(cleaned_amount)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "la gust", "după gust", "opțional"
        name = re.sub(r'\b(la gust|după gust|op[țt]ional|pentru decor)\b', '', name, flags=re.IGNORECASE)
        # Удаляем точки и запятые в конце
        name = re.sub(r'[.,;]+\s*$', '', name)
        # Удаляем предлоги "de" в начале
        name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
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
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_container = self.soup.find('div', class_='wp-block-digitalag-moddepreparare')
        
        if not instructions_container:
            return None
        
        # Находим все параграфы с инструкциями (пропускаем заголовок h2, h3)
        paragraphs = instructions_container.find_all('p')
        
        for p in paragraphs:
            step_text = p.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            
            # Пропускаем параграфы с ссылками на другие рецепты или рекламой
            # (обычно содержат "Descoperă", "Dacă vrei", "îți recomandăm", links)
            if not step_text:
                continue
            
            # Пропускаем если слишком длинный (более 500 символов - вероятно описание, а не инструкция)
            if len(step_text) > 500:
                continue
            
            # Пропускаем рекламные фразы
            skip_phrases = [
                'descoperă și',
                'dacă vrei să',
                'îți recomandăm',
                'poți savura',
                'este apreciat',
                'este unul dintre',
            ]
            
            should_skip = False
            for phrase in skip_phrases:
                if phrase in step_text.lower():
                    should_skip = True
                    break
            
            if not should_skip:
                steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        category = None
        
        # Ищем в div.detalii где указан "tipul preparatului:"
        time_div = self.soup.find('div', class_='time')
        if time_div:
            detalii_div = time_div.find('div', class_='detalii')
            if detalii_div:
                # Ищем div с текстом "tipul preparatului:"
                for dificultate in detalii_div.find_all('div', class_='dificultate'):
                    text_div = dificultate.find('div', class_='text')
                    if text_div:
                        text = text_div.get_text(strip=True)
                        if 'tipul preparatului:' in text.lower():
                            # Извлекаем категорию после двоеточия
                            category = re.sub(r'tipul preparatului:\s*', '', text, flags=re.IGNORECASE)
                            category = self.clean_text(category)
                            break
                
                # Если не нашли, извлекаем из класса detalii (например, "detalii aluaturi")
                if not category:
                    class_attr = detalii_div.get('class', [])
                    for cls in class_attr:
                        if cls != 'detalii':
                            category = cls.capitalize()
                            break
        
        # Если не нашли в div.time, ищем в JSON-LD
        if not category:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    
                    # Ищем articleSection
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list) and sections:
                                    category = self.clean_text(sections[0])
                                elif isinstance(sections, str):
                                    category = self.clean_text(sections)
                                break
                    
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return category
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем в div.detalii
        time_div = self.soup.find('div', class_='time')
        if time_div:
            detalii_div = time_div.find('div', class_='detalii')
            if detalii_div:
                for dificultate in detalii_div.find_all('div', class_='dificultate'):
                    text_div = dificultate.find('div', class_='text')
                    if text_div:
                        text = text_div.get_text(strip=True)
                        
                        # Проверяем различные варианты текста времени
                        time_patterns = {
                            'prep': r'timp\s+de\s+preparare[:\s]+(.+)',
                            'cook': r'timp\s+de\s+[gă]+tire[:\s]+(.+)',
                            'total': r'timp\s+total[:\s]+(.+)'
                        }
                        
                        pattern = time_patterns.get(time_type)
                        if pattern:
                            match = re.search(pattern, text.lower())
                            if match:
                                time_value = match.group(1)
                                time_value = self.clean_text(time_value)
                                # Нормализуем "minute" -> "minutes"
                                time_value = re.sub(r'\bminute\b', 'minutes', time_value, flags=re.IGNORECASE)
                                return time_value
        
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
        # Ищем в первом параграфе после заголовка (обычно там описание/заметка)
        article = self.soup.find('article', class_='articol')
        if article:
            # Ищем параграф с классом "content first"
            first_content = article.find('p', class_='content first')
            if first_content:
                text = first_content.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Разбиваем на предложения и берем последнее
                sentences = [s.strip() for s in text.split('.') if s.strip()]
                if sentences:
                    # Возвращаем последнее предложение
                    return sentences[-1] + '.'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем keywords в Article
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                tags.extend(keywords)
                            elif isinstance(keywords, str):
                                tags = [k.strip() for k in keywords.split(',') if k.strip()]
                            break
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Удаляем дубликаты, сохраняя порядок
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            return ','.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем главное изображение в div.main_photo
        main_photo = self.soup.find('div', class_='main_photo')
        if main_photo:
            img = main_photo.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем image/thumbnailUrl
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article':
                            if 'image' in item:
                                img = item['image']
                                if isinstance(img, str):
                                    urls.append(img)
                                elif isinstance(img, list):
                                    urls.extend([i for i in img if isinstance(i, str)])
                                elif isinstance(img, dict) and 'url' in img:
                                    urls.append(img['url'])
                            
                            if 'thumbnailUrl' in item:
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
    # Обрабатываем папку preprocessed/hellotaste_ro
    recipes_dir = os.path.join("preprocessed", "hellotaste_ro")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(HellotasteRoExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python hellotaste_ro.py")


if __name__ == "__main__":
    main()
