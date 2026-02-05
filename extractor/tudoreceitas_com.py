"""
Экстрактор данных рецептов для сайта tudoreceitas.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TudoReceitasExtractor(BaseRecipeExtractor):
    """Экстрактор для tudoreceitas.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Обрабатываем массив
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Обрабатываем один объект
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем префикс "Receita de "
            name = re.sub(r'^Receita de\s+', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'^Receita de\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text()
            title = re.sub(r'^Receita de\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем список ингредиентов
        ingredient_list = self.soup.find('ul', class_=re.compile(r'ingredient', re.I))
        if not ingredient_list:
            ingredient_list = self.soup.find('div', class_=re.compile(r'ingredient', re.I))
        
        if ingredient_list:
            items = ingredient_list.find_all('li')
            if not items:
                items = ingredient_list.find_all('span')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 xícara de Farinha" или "800 gramas de frango"
            
        Returns:
            dict: {"name": "Farinha", "units": "xícara", "amount": 1} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для португальского формата: "количество единица de название"
        # Примеры: "1 xícara de Farinha", "800 gramas de frango", "2 dentes de alho"
        pattern = r'^([\d\s/.,]+)?\s*(unidade|xícara|xícaras|colher de sopa|colheres de sopa|colher de chá|colheres de chá|colher de café|gramas?|quilogramas?|g|kg|litros?|l|ml|mililitros?|pitadas?|taças?|taça|copos?|copo|dentes?|dente|tabletes?|tablete)?\s*(?:de\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей
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
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Convert float to int if it's a whole number
        if amount is not None and isinstance(amount, float) and amount.is_integer():
            amount = int(amount)
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {step['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_list = self.soup.find('ol', class_=re.compile(r'instruction', re.I))
        if not instructions_list:
            instructions_list = self.soup.find('div', class_=re.compile(r'instruction', re.I))
        
        if instructions_list:
            step_items = instructions_list.find_all('li')
            if not step_items:
                step_items = instructions_list.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not re.match(r'^\d+\.', step_text):
                        steps.append(f"{idx}. {step_text}")
                    else:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Из meta тега
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с советами или дополнительной информацией
        # Попробуем разные варианты, исключая tooltips
        notes_patterns = [
            ('div', re.compile(r'nota|dica|conselho', re.I)),
            ('p', re.compile(r'nota|dica|conselho', re.I)),
            ('div', re.compile(r'tip|note|advice', re.I))
        ]
        
        for tag, pattern in notes_patterns:
            notes_section = self.soup.find(tag, class_=pattern)
            # Пропускаем tooltip элементы
            if notes_section and 'tooltip' not in str(notes_section.get('class', [])):
                text = self.clean_text(notes_section.get_text(separator=' ', strip=True))
                if text and len(text) > 20:  # Игнорируем слишком короткие тексты
                    return text
        
        # Попробуем найти секцию после инструкций
        # В некоторых случаях заметки могут быть в абзаце после рецепта
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Некоторые сайты добавляют notes в JSON-LD под другими ключами
            for key in ['notes', 'cookingMethod', 'recipeTips']:
                if key in recipe_data:
                    return self.clean_text(str(recipe_data[key]))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Также можем поискать в JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                tags_list.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
            elif isinstance(keywords, list):
                tags_list.extend([str(tag).strip() for tag in keywords if tag])
        
        # Если тегов нет, можно попробовать извлечь из контента
        # Например, из заголовка или категории
        if not tags_list:
            dish_name = self.extract_dish_name()
            if dish_name:
                # Извлекаем ключевые слова из названия
                words = re.findall(r'\b\w+\b', dish_name.lower())
                # Фильтруем стоп-слова
                stopwords = {'de', 'da', 'do', 'com', 'e', 'em', 'a', 'o', 'para', 'receita'}
                tags_list = [w for w in words if w not in stopwords and len(w) > 3]
        
        # Убираем дубликаты
        if tags_list:
            seen = set()
            unique_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in seen and len(tag) > 2:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Дополнительно из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Убираем дубликаты и возвращаем через запятую
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
    """Обработка всех HTML файлов из директории preprocessed/tudoreceitas_com"""
    import os
    
    # Находим корневую директорию проекта
    current_dir = Path(__file__).parent.parent
    preprocessed_dir = current_dir / "preprocessed" / "tudoreceitas_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обрабатываем директорию: {preprocessed_dir}")
        process_directory(TudoReceitasExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python extractor/tudoreceitas_com.py")


if __name__ == "__main__":
    main()
