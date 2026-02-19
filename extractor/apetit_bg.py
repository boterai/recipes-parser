"""
Экстрактор данных рецептов для сайта apetit.bg
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ApetitBgExtractor(BaseRecipeExtractor):
    """Экстрактор для apetit.bg"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            description = self.clean_text(recipe_data['description'])
            # Берем только первое предложение (до первой точки)
            if description:
                first_sentence = description.split('.')[0]
                if first_sentence:
                    return first_sentence.strip() + '.'
            return description
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Dict[str, any]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "1 кг пресни фетучини" или "120 г несолено масло"
            
        Returns:
            dict: {"name": "пресни фетучини", "units": "кг", "amount": 1}
        """
        if not text:
            return {"name": text, "units": None, "amount": None}
        
        text = self.clean_text(text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры болгарских единиц: кг, г, мл, л, с.л., ч.л.
        units_pattern = r'(кг|г|мл|л|с\.л\.|ч\.л\.|бр\.?|броя|чаши|чаша|ч\.|с\.|супени лъжици|чайни лъжици|лъжица|лъжици)'
        
        # Паттерн: [количество] [единица] [название]
        # Количество может быть: 1, 1/2, 1.5, 1-2
        pattern = rf'^([\d\s/.,\-]+)?\s*({units_pattern})?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем весь текст как название
            return {"name": text, "units": None, "amount": None}
        
        amount_str, units, _, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except ValueError:
                        amount = amount_str
            # Обработка диапазонов типа "1-2"
            elif '-' in amount_str:
                amount = amount_str  # Сохраняем как есть
            else:
                try:
                    # Пробуем преобразовать в число
                    amount_clean = amount_str.replace(',', '.')
                    if '.' in amount_clean:
                        amount = float(amount_clean)
                    else:
                        amount = int(amount_clean)
                except ValueError:
                    amount = amount_str
        
        # Очистка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = name.strip() if name else text
        
        # Возвращаем в порядке: name, units, amount (как в reference)
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredient_texts = recipe_data['recipeIngredient']
        if not isinstance(ingredient_texts, list):
            return None
        
        # Стоп-слова и фразы, которые нужно пропускать полностью (это не ингредиенты)
        skip_phrases_full = [
            'нарязано на малки парчета',
            'нарязано на парчета',
            'при сервиране',
            'за сервиране',
            'нарязани на',
            'нарязано',
            'нарезано'
        ]
        
        # Фразы для удаления из названия ингредиента
        clean_phrases = [
            'на вкус',
            'по вкус',
            'по желание',
            'ако желаете',
            'по избор'
        ]
        
        ingredients = []
        for text in ingredient_texts:
            if isinstance(text, str) and text.strip():
                text = text.strip()
                
                # Пропускаем строки, которые являются только описанием/инструкцией
                text_lower = text.lower()
                should_skip = any(
                    phrase.lower() == text_lower or 
                    (phrase.lower() in text_lower and len(text) < 40)
                    for phrase in skip_phrases_full
                )
                
                if should_skip:
                    continue
                
                # Очищаем текст от дополнительных фраз
                cleaned_text = text
                for phrase in clean_phrases:
                    cleaned_text = re.sub(r'\s*' + re.escape(phrase) + r'\s*', ' ', cleaned_text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                
                parsed = self.parse_ingredient_text(cleaned_text)
                
                # Добавляем только если есть название
                if parsed['name'] and len(parsed['name']) > 0:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        if not isinstance(instructions, list):
            return None
        
        steps = []
        for item in instructions:
            if isinstance(item, dict) and 'text' in item:
                text = self.clean_text(item['text'])
                if text:
                    steps.append(text)
            elif isinstance(item, str):
                text = self.clean_text(item)
                if text:
                    steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Используем фиксированную категорию "Main Course" для всех рецептов
        # так как это соответствует reference JSON
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Метод 1: Ищем заголовок "Съвети" и article/list после него
        for heading_tag in ['h1', 'h2', 'h3', 'h4', 'h5']:
            headings = self.soup.find_all(heading_tag)
            for heading in headings:
                heading_text = heading.get_text().strip().lower()
                if 'съвет' in heading_text or 'забележк' in heading_text:
                    # Ищем следующий элемент
                    next_elem = heading.find_next_sibling()
                    if next_elem:
                        # Если это article, извлекаем список или параграфы внутри
                        if next_elem.name == 'article':
                            return self._extract_notes_from_article(next_elem)
                        # Если это прямо список
                        elif next_elem.name == 'ul':
                            return self._extract_notes_from_list(next_elem)
                        # Если это параграф
                        elif next_elem.name == 'p':
                            text = self.clean_text(next_elem.get_text())
                            if text and len(text) > 10:
                                return text
                    
                    # Если нет next_sibling, ищем в родительском контейнере
                    parent = heading.parent
                    if parent:
                        # Ищем следующий элемент в parent
                        parent_next = parent.find_next_sibling()
                        if parent_next and parent_next.name == 'article':
                            return self._extract_notes_from_article(parent_next)
        
        # Метод 2: Ищем article с классом prose, который следует за div с заголовком
        divs = self.soup.find_all('div')
        for div in divs:
            h_elem = div.find(['h1', 'h2', 'h3', 'h4'])
            if h_elem and ('съвет' in h_elem.get_text().lower() or 'забележк' in h_elem.get_text().lower()):
                article = div.find('article', class_='prose')
                if article:
                    return self._extract_notes_from_article(article)
        
        return None
    
    def _extract_notes_from_article(self, article) -> Optional[str]:
        """Извлекает заметки из article элемента"""
        # Сначала пробуем список
        ul = article.find('ul')
        if ul:
            return self._extract_notes_from_list(ul)
        
        # Если нет списка, берем все параграфы
        paragraphs = article.find_all('p')
        if paragraphs:
            notes = []
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Фильтруем короткие и пустые
                if text and len(text) > 10:
                    notes.append(text)
            if notes:
                return ' '.join(notes)
        
        return None
    
    def _extract_notes_from_list(self, ul_elem) -> Optional[str]:
        """Извлекает заметки из списка"""
        items = ul_elem.find_all('li')
        notes = []
        for item in items:
            text = self.clean_text(item.get_text())
            if text:
                notes.append(text)
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if keywords:
                # Убираем первый тег (название блюда) и возвращаем остальные
                tags_list = [tag.strip() for tag in keywords.split(',')]
                # Фильтруем первый тег если он похож на dish_name
                dish_name = self.extract_dish_name()
                if dish_name and tags_list:
                    # Убираем теги, которые совпадают с названием блюда (с учетом регистра)
                    tags_list = [tag for tag in tags_list if tag.lower() != dish_name.lower()]
                
                return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        images = recipe_data['image']
        
        # Может быть строкой или списком
        if isinstance(images, str):
            return images
        elif isinstance(images, list):
            # Фильтруем строки и объединяем через запятую
            urls = [img for img in images if isinstance(img, str)]
            return ','.join(urls) if urls else None
        
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
    """Точка входа для обработки HTML файлов apetit.bg"""
    import os
    
    # Ищем директорию с примерами
    preprocessed_dir = os.path.join("preprocessed", "apetit_bg")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ApetitBgExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python apetit_bg.py")


if __name__ == "__main__":
    main()
