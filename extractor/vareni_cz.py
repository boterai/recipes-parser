"""
Экстрактор данных рецептов для сайта vareni.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VarieniCzExtractor(BaseRecipeExtractor):
    """Экстрактор для vareni.cz"""
    
    def __init__(self, html_path: str):
        """Инициализация экстрактора"""
        super().__init__(html_path)
        self.json_ld_data = self._extract_json_ld()
    
    def _extract_json_ld(self) -> Optional[dict]:
        """
        Извлечение структурированных данных JSON-LD из HTML
        
        Returns:
            Словарь с данными рецепта или None
        """
        try:
            # Ищем все script теги с JSON-LD
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                if not script.string:
                    continue
                
                try:
                    data = json.loads(script.string)
                    
                    # Проверяем, что это данные рецепта
                    if isinstance(data, dict) and data.get('@type') == 'Recipe':
                        return data
                    
                    # Если это массив, ищем объект Recipe
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                
                except json.JSONDecodeError:
                    continue
            
            return None
        
        except Exception as e:
            print(f"Ошибка при извлечении JSON-LD: {e}")
            return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes"
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
        # Сначала пробуем из JSON-LD
        if self.json_ld_data and 'name' in self.json_ld_data:
            return self.clean_text(self.json_ld_data['name'])
        
        # Fallback: ищем в HTML
        title_tag = self.soup.find('h1', {'data-test-id': 'recipe-detail-title'})
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        # Еще один fallback
        h1_tag = self.soup.find('h1')
        if h1_tag:
            return self.clean_text(h1_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        if self.json_ld_data and 'description' in self.json_ld_data:
            return self.clean_text(self.json_ld_data['description'])
        
        # Fallback: ищем в HTML
        # Ищем p после h1 заголовка
        title_tag = self.soup.find('h1', {'data-test-id': 'recipe-detail-title'})
        if title_tag:
            desc_tag = title_tag.find_next('p')
            if desc_tag:
                return self.clean_text(desc_tag.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов в формате JSON array
        
        Returns:
            JSON строка с массивом ингредиентов [{name, amount, units}]
        """
        ingredients = []
        
        # Сначала пробуем извлечь из HTML (там есть структурированные данные)
        # Ищем все контейнеры ингредиентов
        ingredient_items = self.soup.find_all('div', class_=re.compile(r'sc-y46x99-5'))
        
        if ingredient_items:
            for item in ingredient_items:
                # Ищем название ингредиента
                name_span = item.find('span', class_=re.compile(r'sc-y46x99-7'))
                if not name_span:
                    continue
                
                # Извлекаем название
                name_text = name_span.get_text(strip=True)
                
                # Ищем количество и единицы измерения
                amount_span = name_span.find('span', class_=re.compile(r'sc-y46x99-8'))
                
                amount = None
                units = None
                
                if amount_span:
                    # Удаляем этот span из текста названия
                    amount_text = amount_span.get_text(strip=True)
                    name_text = name_text.replace(amount_text, '').strip()
                    
                    # Парсим количество и единицы
                    amount_text = self.clean_text(amount_text)
                    
                    # Пытаемся разделить на количество и единицы
                    # Формат: "200 g", "1 špetka", "2 ks"
                    parts = amount_text.split(None, 1)
                    if len(parts) >= 1:
                        amount = parts[0]
                    if len(parts) >= 2:
                        units = parts[1]
                
                ingredient = {
                    "name": self.clean_text(name_text),
                    "units": units,
                    "amount": amount
                }
                ingredients.append(ingredient)
        
        # Если не нашли в HTML, пробуем JSON-LD (но там нет структуры)
        if not ingredients and self.json_ld_data and 'recipeIngredient' in self.json_ld_data:
            for ing_text in self.json_ld_data['recipeIngredient']:
                # Простой парсинг: пытаемся извлечь количество из начала строки
                ing_text = self.clean_text(ing_text)
                
                # Пробуем найти число в начале
                match = re.match(r'^(\d+(?:[.,]\d+)?)\s*(\S+)?\s*(.+)$', ing_text)
                if match:
                    amount = match.group(1)
                    units = match.group(2) if match.group(2) else None
                    name = match.group(3)
                else:
                    amount = None
                    units = None
                    name = ing_text
                
                ingredient = {
                    "name": name,
                    "units": units,
                    "amount": amount
                }
                ingredients.append(ingredient)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Сначала пробуем из JSON-LD
        if self.json_ld_data and 'recipeInstructions' in self.json_ld_data:
            recipe_instructions = self.json_ld_data['recipeInstructions']
            
            # Флаг для остановки сбора инструкций при встрече заметки/совета
            found_note_or_tip = False
            
            for step in recipe_instructions:
                if isinstance(step, dict):
                    # Это HowToStep
                    text = step.get('text', '')
                    if text:
                        text = self.clean_text(text)
                        
                        # Если встретили заметку или совет, прекращаем сбор инструкций
                        if text.startswith('Poznámka:') or text.startswith('!TIP') or text.startswith('!'):
                            found_note_or_tip = True
                        
                        # Добавляем только если это не заметка/совет и мы еще не встретили их
                        if not found_note_or_tip:
                            instructions.append(text)
                            
                elif isinstance(step, str):
                    text = self.clean_text(step)
                    
                    if text.startswith('Poznámka:') or text.startswith('!TIP') or text.startswith('!'):
                        found_note_or_tip = True
                    
                    if not found_note_or_tip:
                        instructions.append(text)
        
        # Fallback: ищем в HTML
        if not instructions:
            # Ищем список шагов
            steps_list = self.soup.find('ol')
            if steps_list:
                steps = steps_list.find_all('li')
                found_note_or_tip = False
                
                for step in steps:
                    text = self.clean_text(step.get_text())
                    
                    if text and (text.startswith('Poznámka:') or text.startswith('!TIP') or text.startswith('!')):
                        found_note_or_tip = True
                    
                    if text and not found_note_or_tip:
                        instructions.append(text)
        
        if instructions:
            # Объединяем все шаги в одну строку
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пробуем из JSON-LD
        if self.json_ld_data and 'recipeCategory' in self.json_ld_data:
            return self.clean_text(self.json_ld_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        if self.json_ld_data and 'prepTime' in self.json_ld_data:
            return self.parse_iso_duration(self.json_ld_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        if self.json_ld_data and 'cookTime' in self.json_ld_data:
            return self.parse_iso_duration(self.json_ld_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        if self.json_ld_data and 'totalTime' in self.json_ld_data:
            return self.parse_iso_duration(self.json_ld_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/примечаний"""
        notes = []
        
        # Ищем заметки в recipeInstructions
        if self.json_ld_data and 'recipeInstructions' in self.json_ld_data:
            recipe_instructions = self.json_ld_data['recipeInstructions']
            
            for step in recipe_instructions:
                if isinstance(step, dict):
                    text = step.get('text', '')
                    if text:
                        text = self.clean_text(text)
                        # Берем только шаги, которые начинаются с "Poznámka:"
                        if text.startswith('Poznámka:'):
                            # Убираем префикс "Poznámka:"
                            note_text = text.replace('Poznámka:', '').strip()
                            notes.append(note_text)
                elif isinstance(step, str):
                    text = self.clean_text(step)
                    if text.startswith('Poznámka:'):
                        note_text = text.replace('Poznámka:', '').strip()
                        notes.append(note_text)
        
        if notes:
            return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем из JSON-LD keywords
        if self.json_ld_data and 'keywords' in self.json_ld_data:
            keywords = self.json_ld_data['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join([self.clean_text(k) for k in keywords])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Пробуем из JSON-LD
        if self.json_ld_data and 'image' in self.json_ld_data:
            images = self.json_ld_data['image']
            if isinstance(images, list):
                image_urls.extend(images)
            elif isinstance(images, str):
                image_urls.append(images)
        
        # Дополнительно: ищем основное изображение в HTML
        if not image_urls:
            main_img = self.soup.find('img', class_=re.compile(r'sc-lbn1ms-0'))
            if main_img and main_img.get('src'):
                image_urls.append(main_img['src'])
        
        if image_urls:
            # Возвращаем как строку, разделенную запятыми
            return ','.join(image_urls)
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь со всеми полями рецепта
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
    """
    Обработка всех HTML файлов из директории preprocessed/vareni_cz
    """
    # Определяем путь к директории с HTML файлами
    current_file = Path(__file__)
    repo_root = current_file.parent.parent
    preprocessed_dir = repo_root / 'preprocessed' / 'vareni_cz'
    
    if not preprocessed_dir.exists():
        print(f"Директория {preprocessed_dir} не найдена")
        return
    
    print(f"Обработка файлов из: {preprocessed_dir}")
    print("=" * 60)
    
    # Обрабатываем все HTML файлы
    process_directory(VarieniCzExtractor, str(preprocessed_dir))


if __name__ == '__main__':
    main()
