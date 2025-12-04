"""
Экстрактор данных рецептов для сайта ricardocuisine.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

from extractor.base import BaseRecipeExtractor, process_directory


class RicardoCuisineExtractor(BaseRecipeExtractor):
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                data = json.loads(script_content.strip())
                
                # Проверяем, что это рецепт
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except json.JSONDecodeError:
                continue
        
        return {}
    
    def extract_dish_name(self) -> str:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'name' in json_data:
            return json_data['name'].strip()
        
        # Резервный вариант - из заголовка
        title = self.soup.find('h1', class_='c-recipe__title')
        if title:
            return title.get_text(strip=True)
        
        return ""
    
    def extract_description(self) -> str:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'description' in json_data:
            return json_data['description'].strip()
        
        # Резервный вариант
        description = self.soup.find('div', class_='c-recipe__description')
        if description:
            return description.get_text(strip=True)
        
        return ""
    
    def extract_ingredients(self) -> str:
        """Извлечение ингредиентов с количествами"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeIngredient' in json_data:
            ingredients_list = json_data['recipeIngredient']
            
            # Очищаем каждый ингредиент
            cleaned = []
            for ing in ingredients_list:
                # Удаляем лишние пробелы и табуляции
                cleaned_ing = ' '.join(ing.split()).strip()
                cleaned.append(cleaned_ing)
            
            return ', '.join(cleaned).lower()
        
        return ""
    
    def extract_ingredients_names(self) -> list:
        """Извлечение только названий ингредиентов без количеств"""
        # Из JSON-LD получаем полные ингредиенты
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeIngredient' in json_data:
            ingredients_list = json_data['recipeIngredient']
            names = []
            
            for ing in ingredients_list:
                # Удаляем лишние пробелы и табуляции
                cleaned = ' '.join(ing.split()).strip()
                
                # Убираем примечания в скобках
                cleaned = re.sub(r'\([^)]+\)', '', cleaned).strip()
                
                # Паттерн: после "de" или "d'" идет название ингредиента
                # Пример: "125 ml (1/2 tasse) de bouillon de bœuf"
                match = re.search(r'\bde\s+(.+?)(?:\s*,|$)', cleaned, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                else:
                    # Если нет "de", пробуем найти последнюю часть после единиц измерения
                    # Убираем числа и единицы в начале
                    match = re.search(r'^[\d\s/().]+(?:ml|g|lb|tasse|c\.\s*à\s*(?:soupe|thé))\s+(.+?)(?:\s*,|$)', cleaned, re.IGNORECASE)
                    if match:
                        name = match.group(1).strip()
                    else:
                        # Последняя попытка - просто последнее слово/фраза
                        parts = cleaned.split()
                        if parts:
                            # Пропускаем числа и единицы измерения
                            name = ' '.join([p for p in parts if not re.match(r'^[\d/().]+$', p) and p.lower() not in ['ml', 'g', 'lb', 'tasse', 'c.', 'à', 'soupe', 'thé']])
                        else:
                            continue
                
                # Очистка названия
                name = name.strip().rstrip(',.')
                # Убираем "d'" в начале
                name = re.sub(r"^d['\']", '', name).strip()
                # Убираем лишние детали типа "de 340 g"
                name = re.sub(r'\s+de\s+\d+.*$', '', name).strip()
                # Убираем дополнительные описания (после запятой)
                name = re.split(r',', name)[0].strip()
                
                if name and len(name) > 1:
                    names.append(name.lower())
            
            return names
        
        return []
    
    def extract_step_by_step(self) -> str:
        """Извлечение пошаговых инструкций"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeInstructions' in json_data:
            instructions = json_data['recipeInstructions']
            steps = []
            
            for section in instructions:
                if isinstance(section, dict) and section.get('@type') == 'HowToSection':
                    # Получаем шаги из секции
                    for step in section.get('itemListElement', []):
                        if isinstance(step, dict) and step.get('@type') == 'HowToStep':
                            text = step.get('text', '').strip()
                            # Удаляем HTML теги если есть
                            text = re.sub(r'<[^>]+>', '', text)
                            # Нормализуем пробелы
                            text = ' '.join(text.split())
                            if text:
                                steps.append(text)
            
            return ' '.join(steps)
        
        return ""
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'aggregateRating' in json_data:
            rating_data = json_data['aggregateRating']
            if 'ratingValue' in rating_data:
                try:
                    return float(rating_data['ratingValue'])
                except (ValueError, TypeError):
                    pass
        
        return None
    
    def extract_category(self) -> str:
        """Извлечение категории рецепта"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeCategory' in json_data:
            return json_data['recipeCategory'].strip()
        
        return ""
    
    def extract_prep_time(self) -> str:
        """Извлечение времени подготовки"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'prepTime' in json_data:
            # Конвертируем ISO 8601 duration в человекочитаемый формат
            time_str = json_data['prepTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def extract_cook_time(self) -> str:
        """Извлечение времени приготовления"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'cookTime' in json_data:
            time_str = json_data['cookTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def extract_total_time(self) -> str:
        """Извлечение общего времени"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'totalTime' in json_data:
            time_str = json_data['totalTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def _convert_iso_duration(self, duration: str) -> str:
        """Конвертирует ISO 8601 duration (PT30M) в читаемый формат (30 minutes)"""
        if not duration:
            return ""
        
        # Парсим формат PT30M, PT1H30M и т.д.
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        h_match = re.search(r'(\d+)H', duration)
        if h_match:
            hours = int(h_match.group(1))
        
        # Извлекаем минуты
        m_match = re.search(r'(\d+)M', duration)
        if m_match:
            minutes = int(m_match.group(1))
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else ""
    
    def extract_servings(self) -> str:
        """Извлечение количества порций"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeYield' in json_data:
            yield_str = json_data['recipeYield']
            # Извлекаем число из строки типа "4 portion(s)"
            match = re.search(r'(\d+)', yield_str)
            if match:
                return match.group(1)
        
        return ""
    
    def extract_difficulty_level(self) -> str:
        """Извлечение уровня сложности"""
        # На ricardocuisine.com обычно нет явного уровня сложности
        # Можно попробовать определить по времени
        total_time = self.extract_total_time()
        if total_time:
            # Простая эвристика
            if 'hour' in total_time:
                return "Medium"
            else:
                # Парсим минуты
                match = re.search(r'(\d+)\s+minute', total_time)
                if match:
                    minutes = int(match.group(1))
                    if minutes <= 30:
                        return "Easy"
                    elif minutes <= 60:
                        return "Medium"
                    else:
                        return "Hard"
        
        return "Medium"
    
    def extract_notes(self) -> str:
        """Извлечение заметок и примечаний"""
        # Ищем примечания от команды Ricardo в HTML
        note_article = self.soup.find('article', class_='c-recipe-note')
        if note_article:
            # Проверяем, что это не персональная заметка
            if 'c-recipe-note--personal' not in note_article.get('class', []):
                note_body = note_article.find('div', class_='c-recipe-note__body')
                if note_body:
                    # Извлекаем текст и очищаем HTML entities
                    notes = note_body.get_text(strip=True)
                    # Убираем &nbsp; и другие HTML entities
                    notes = notes.replace('\xa0', ' ')
                    return notes.strip()
        
        # Резервный вариант - ищем в общей секции notes
        notes_section = self.soup.find('section', class_='c-recipe-notes')
        if notes_section:
            note_body = notes_section.find('div', class_='c-recipe-note__body')
            if note_body:
                notes = note_body.get_text(strip=True)
                notes = notes.replace('\xa0', ' ')
                return notes.strip()
        
        return ""
    
    def extract_tags(self) -> list:
        """Извлечение тегов"""
        tags = []
        
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data:
            # Основная категория
            if 'recipeCategory' in json_data:
                tags.append(json_data['recipeCategory'].strip().lower())
            
            # Подкатегории
            if 'recipeSubCategories' in json_data:
                for cat in json_data['recipeSubCategories']:
                    tags.append(cat.strip().lower())
            
            # Ключевые слова
            if 'keywords' in json_data:
                keywords = json_data['keywords']
                if isinstance(keywords, str):
                    for kw in keywords.split(','):
                        tags.append(kw.strip().lower())
        
        # Убираем дубликаты
        return list(set(tags))
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        ingredients_names = self.extract_ingredients_names()
        step_by_step = self.extract_step_by_step()
        rating = self.extract_rating()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        difficulty_level = self.extract_difficulty_level()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name if dish_name else None,
            "description": description if description else None,
            "ingredients": ingredients if ingredients else None,
            "step_by_step": step_by_step if step_by_step else None,
            "rating": rating,
            "category": category if category else None,
            "prep_time": prep_time if prep_time else None,
            "cook_time": cook_time if cook_time else None,
            "total_time": total_time if total_time else None,
            "difficulty_level": difficulty_level if difficulty_level else None,
            "notes": notes if notes else None,
            "ingredients_names": ', '.join(ingredients_names) if ingredients_names else None,
            "tags": ', '.join(tags) if tags else None
        }


def main():
    """Основная функция для обработки файлов"""
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python ricardocuisine_com.py <путь_к_директории>")
        sys.exit(1)
    
    directory = sys.argv[1]
    process_directory(RicardoCuisineExtractor, directory)


if __name__ == "__main__":
    main()
