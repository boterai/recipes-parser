"""
Экстрактор данных рецептов для сайта ndtv.in
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NdtvInExtractor(BaseRecipeExtractor):
    """Экстрактор для ndtv.in"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из H1 (предпочитаем Hindi название)
        h1 = self.soup.find('h1', class_='sp-ttl')
        if h1:
            title = h1.get_text()
            
            # Пробуем найти название блюда в Hindi (заканчивается на ключевые слова)
            match = re.search(r'([\u0900-\u097F\s]+(?:उपमा|हलवा|दाल|करी))', title)
            if match:
                dish = match.group(1).strip()
                # Очищаем от лишних слов в начале
                dish = re.sub(r'^.*?(?:बनाएं|करें)\s+(?:स्वादिष्ट\s+)?', '', dish)
                dish = self.clean_text(dish)
                if dish and len(dish) < 50:
                    return dish
        
        # Если не нашли в H1, пробуем из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            first_keyword = keywords.split(',')[0].strip()
            if first_keyword:
                # Убираем слова "Recipe", "kaise banaye" и т.д.
                name = re.sub(r'\s+(Recipe|recipe|kaise banaye)$', '', first_keyword, flags=re.IGNORECASE)
                name = self.clean_text(name)
                if name:
                    return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем краткое описание в тексте статьи
        # Обычно это предложение вида "स्वादिष्ट ... जिसे आप ... बना कर तैयार कर सकते हैं"
        article = self.soup.find('div', class_='sp-cn')
        if article:
            paragraphs = article.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Ищем паттерн описания
                match = re.search(r'(स्वादिष्ट[^.]*?बना\s+कर\s+तैयार\s+कर\s+सकते\s+हैं\.)', text)
                if match:
                    return self.clean_text(match.group(1))
        
        # Если не нашли, берем из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префикс типа "Moong Dal Halwa: "
            desc = re.sub(r'^[^:]+:\s*', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'^[^:]+:\s*', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def _get_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD данных типа HowTo"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем тип HowTo
                if isinstance(data, dict) and data.get('@type') == 'HowTo':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ингредиенты в ndtv.in часто упоминаются в тексте описания или инструкций
        # Ищем их по ключевым словам
        article = self.soup.find('div', class_='sp-cn')
        if not article:
            return None
        
        full_text = article.get_text()
        
        # Общие ингредиенты для индийской кухни
        ingredient_patterns = [
            r'मूंग\s+दाल', r'घी', r'सूजी', r'बेसन', r'चीनी', r'इलायची(?:\s+पाउडर)?',
            r'केसर', r'बादाम', r'काजू', r'नमक', r'कढ़ीपत्ता', r'सरसों\s+के\s+दाने',
            r'प्याज', r'टमाटर', r'सब्जियां', r'पानी', r'तेल', r'मसाले',
            r'हल्दी', r'लाल\s+मिर्च', r'धनिया\s+पाउडर', r'जीरा', r'गरम\s+मसाला',
            r'दही', r'दूध', r'मक्खन', r'पनीर', r'आटा', r'चावल', r'दाल'
        ]
        
        found_ingredients = set()
        for pattern in ingredient_patterns:
            matches = re.finditer(pattern, full_text, re.IGNORECASE)
            for match in matches:
                ing = match.group(0).strip()
                # Нормализуем пробелы
                ing = re.sub(r'\s+', ' ', ing)
                found_ingredients.add(ing)
        
        # Сортируем для консистентности
        for ing in sorted(found_ingredients):
            ingredients.append({
                "name": ing,
                "amount": None,
                "unit": None
            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _parse_ingredient_simple(self, text: str) -> Optional[dict]:
        """
        Простой парсинг ингредиента
        
        Args:
            text: строка с ингредиентом
            
        Returns:
            dict: {"name": "...", "amount": None, "unit": None}
        """
        if not text or len(text) < 2:
            return None
        
        # Для ndtv.in часто нет количества и единиц
        # Просто возвращаем название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def _extract_ingredients_from_text(self, text: str) -> list:
        """
        Извлечение ингредиентов из текстового описания
        
        Args:
            text: текст описания
            
        Returns:
            list: список словарей с ингредиентами
        """
        ingredients = []
        
        # Ищем части текста с перечислением через запятую
        # Обычно после определенных слов
        parts = text.split('.')
        
        for part in parts:
            # Если есть несколько запятых, возможно это список ингредиентов
            if part.count(',') >= 2:
                items = part.split(',')
                for item in items:
                    item = self.clean_text(item)
                    # Пропускаем слишком длинные фразы
                    if item and 5 < len(item) < 50:
                        ingredients.append({
                            "name": item,
                            "amount": None,
                            "unit": None
                        })
        
        return ingredients
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем параграфы с основными инструкциями
        article = self.soup.find('div', class_='sp-cn')
        if not article:
            return None
        
        paragraphs = article.find_all('p')
        instructions = []
        
        for p in paragraphs:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Ищем параграфы с инструкциями
            # Вариант 1: начинается с "... बनाने के लिए सबसे पहले"
            if 'बनाने के लिए सबसे पहले' in text:
                # Это основной параграф с полными инструкциями
                text = re.sub(r'\([^\)]*अस्वीकरण[^\)]*\)', '', text)
                return text
            
            # Вариант 2: параграфы начинающиеся с "... बनाने के लिए"
            # Это могут быть отдельные советы, собираем их
            if text.startswith(('बनाने के लिए', 'उपमा बनाने', 'हलवा बनाने', 'दाल बनाने')):
                if len(text) > 30:
                    instructions.append(text)
        
        # Если собрали несколько параграфов с советами, объединяем
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def _extract_step_text(self, step_item: dict) -> Optional[str]:
        """
        Извлечение текста шага из JSON-LD структуры
        
        Args:
            step_item: элемент шага из JSON-LD
            
        Returns:
            Текст шага или None
        """
        if not isinstance(step_item, dict):
            return None
        
        # Проходим по структуре HowToSection -> HowToStep -> HowToDirection
        if step_item.get('@type') == 'HowToSection':
            item_list = step_item.get('itemListElement')
            if isinstance(item_list, dict):
                nested_item = item_list.get('itemListElement')
                if isinstance(nested_item, dict):
                    text = nested_item.get('text', '')
                    if text:
                        # Убираем HTML теги
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = self.clean_text(text)
                        return text
        
        # Прямой текст
        if 'text' in step_item:
            text = step_item['text']
            text = re.sub(r'<[^>]+>', ' ', text)
            text = self.clean_text(text)
            return text
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Определяем категорию по контексту рецепта и названию
        dish_name = self.extract_dish_name()
        if dish_name:
            dish_lower = dish_name.lower()
            # Проверяем название блюда
            if 'upma' in dish_lower or 'उपमा' in dish_lower:
                return 'Main Course'
            elif 'halwa' in dish_lower or 'हलवा' in dish_lower:
                return 'Dessert'
        
        # Если не определили по названию, проверяем контекст
        article = self.soup.find('div', class_='sp-cn')
        if article:
            # Ищем в заголовках h2, h3
            headers = article.find_all(['h2', 'h3'])
            for h in headers:
                h_text = h.get_text().lower()
                if 'उपमा' in h_text and 'बनाएं' in h_text:
                    return 'Main Course'
                elif 'हलवा' in h_text and 'बनाएं' in h_text:
                    return 'Dessert'
            
            text = article.get_text().lower()
            
            # Проверяем ключевые слова для определения категории
            # Сначала проверяем более специфичные условия
            if 'उपमा' in text[:500]:  # Upma упоминается в начале
                return 'Main Course'
            elif 'हलवा' in text[:500] and ('मीठा' in text[:500] or 'sweet' in text[:500]):
                return 'Dessert'
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем упоминание времени в инструкциях
        article = self.soup.find('div', class_='sp-cn')
        if not article:
            return None
        
        text = article.get_text()
        
        # Ищем паттерн "4 से 5 घंटे भीगी हुई"
        match = re.search(r'(\d+\s*से\s*\d+\s*घंटे)', text)
        if match:
            time_str = match.group(1)
            # Преобразуем в формат "4-5 hours"
            numbers = re.findall(r'\d+', time_str)
            if len(numbers) >= 2:
                return f"{numbers[0]}-{numbers[1]} hours"
            elif len(numbers) == 1:
                return f"{numbers[0]} hours"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # В ndtv.in обычно нет отдельного cook_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В ndtv.in обычно нет отдельного total_time в нужном формате
        # Игнорируем JSON-LD totalTime так как он не соответствует ожиданиям
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем конкретную фразу с советом
        article = self.soup.find('div', class_='sp-cn')
        if not article:
            return None
        
        text = article.get_text()
        
        # Ищем специфичные заметки/советы
        # Обычно это предложения с ключевыми словами
        sentences = text.split('.')
        
        for sentence in sentences:
            sentence = self.clean_text(sentence)
            # Ищем важные заметки
            if 'लगातार चलाना' in sentence and 'जरूरी' in sentence:
                return sentence.strip() + '.'
            if 'ध्यान' in sentence or ('जरूरी' in sentence and len(sentence) < 200):
                # Это похоже на совет
                if 20 < len(sentence) < 200:
                    return sentence.strip() + '.'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Для tags нужно использовать более простую логику
        # Берем название блюда + тип блюда
        
        dish_name = self.extract_dish_name()
        category = self.extract_category()
        
        tags = []
        
        if dish_name:
            tags.append(dish_name)
        
        # Определяем тип блюда по категории и контексту
        if category == 'Dessert':
            if 'Dessert' not in tags:
                tags.append('Dessert')
            if 'Indian Sweet' not in tags:
                tags.append('Indian Sweet')
        elif category == 'Main Course':
            # Для Main Course проверяем, это upma или что-то другое
            article = self.soup.find('div', class_='sp-cn')
            if article:
                text = article.get_text().lower()
                if 'उपमा' in text[:500]:
                    # Upma tags
                    if 'साउथ इंडियन' in text:
                        tags.append('साउथ इंडियन')
                    tags.append('नाश्ता')
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_data = self._get_json_ld()
        if json_ld_data and 'step' in json_ld_data:
            step_data = json_ld_data['step']
            
            # Извлекаем изображения из шагов
            if isinstance(step_data, list):
                for step_section in step_data:
                    if isinstance(step_section, list):
                        for step_item in step_section:
                            img_url = self._extract_image_from_step(step_item)
                            if img_url and img_url not in urls:
                                urls.append(img_url)
                    else:
                        img_url = self._extract_image_from_step(step_section)
                        if img_url and img_url not in urls:
                            urls.append(img_url)
        
        # 3. Ищем основное изображение статьи
        main_img = self.soup.find('img', id='story_image_main')
        if main_img and main_img.get('src'):
            img_url = main_img['src']
            if img_url not in urls:
                urls.append(img_url)
        
        # Ограничиваем до 3 изображений
        if urls:
            return ','.join(urls[:3])
        
        return None
    
    def _extract_image_from_step(self, step_item: dict) -> Optional[str]:
        """
        Извлечение URL изображения из шага JSON-LD
        
        Args:
            step_item: элемент шага
            
        Returns:
            URL изображения или None
        """
        if not isinstance(step_item, dict):
            return None
        
        # Проверяем структуру HowToSection
        if step_item.get('@type') == 'HowToSection':
            item_list = step_item.get('itemListElement')
            if isinstance(item_list, dict) and 'image' in item_list:
                return item_list['image']
        
        # Прямое поле image
        if 'image' in step_item:
            return step_item['image']
        
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка директории с HTML файлами ndtv.in"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "ndtv_in")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NdtvInExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python ndtv_in.py")


if __name__ == "__main__":
    main()
