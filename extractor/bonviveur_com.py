"""
Экстрактор данных рецептов для сайта bonviveur.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BonviveurExtractor(BaseRecipeExtractor):
    """Экстрактор для bonviveur.com"""
    
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Получение Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r',\s+la\s+receta.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Убираем часть "Descubre cómo hacer..."
            desc = re.sub(r'\s*Descubre\s+cómo\s+hacer.*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            desc = re.sub(r'\s*Descubre\s+cómo\s+hacer.*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "75 g de puerro" или "1 diente de ajo"
            
        Returns:
            dict: {"name": "puerro", "amount": 75, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн для испанских ингредиентов: "количество единица de название"
        # Примеры: "75 g de puerro", "1 diente de ajo", "2 cucharadas de aceite"
        pattern = r'^([\d,./]+)\s*(g|kg|ml|l|cucharadas?|cucharaditas?|dientes?|rebanadas?|unidades?|obleas?|pizca|pizcas)?\s*(?:de\s+)?(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если нет количества в начале, возможно просто название
            # Проверяем есть ли количество вообще
            if any(char.isdigit() for char in text):
                return None
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Специальная обработка для "obleas para X" - это название, не единица
        if unit and unit.lower() in ['obleas', 'oblea']:
            # Если после "obleas" идет "para", это часть названия
            if name.strip().startswith('para '):
                # "15 obleas para gyozas" -> name="oblea para gyozas", units="unidades"
                name = unit.rstrip('s') + ' ' + name  # "oblea para gyozas"
                unit = 'unidades'
        
        # Обработка количества - конвертируем в число
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            try:
                # Пробуем сконвертировать в int, если не получается - в float
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = amount_str
        
        # Обработка единицы измерения - приводим к единственному числу
        if unit:
            unit = unit.strip().lower()
            # Множественное -> единственное число
            unit_map = {
                'cucharadas': 'cucharadas',
                'cucharada': 'cucharadas',
                'cucharaditas': 'cucharadita',
                'cucharadita': 'cucharadita',
                'dientes': 'diente',
                'diente': 'diente',
                'rebanadas': 'rebanadas',
                'rebanada': 'rebanadas',
                'unidades': 'unidades',
                'unidad': 'unidades',
                'obleas': 'unidades',
                'oblea': 'unidades',
                'pizcas': 'pizca',
                'pizca': 'pizca'
            }
            unit = unit_map.get(unit, unit)
        
        # Очистка названия - убираем (opcional) и подобное
        name = re.sub(r'\s*\(opcional\)\s*', '', name)
        name = re.sub(r'\s+para\s+acompañar.*$', '', name)
        name = re.sub(r'\s+al\s+gusto.*$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_text(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {step['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory']).lower()
        
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
        notes = []
        
        # Ищем параграфы с советами (обычно содержат ключевые слова)
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text()
            text_lower = text.lower()
            
            # Проверяем на наличие ключевых слов советов/альтернатив
            # Ищем конкретные фразы, которые указывают на советы
            keywords = [
                ('también podemos preparar', 50),  # (keyword, min_position)
                ('se pueden comprar', 50),
                ('se puede preparar', 50),
                ('podéis añadir', 50),
                ('podéis personalizar', 50),
                ('también podéis', 50),
                ('si os gusta', 50)
            ]
            
            for keyword, min_pos in keywords:
                pos = text_lower.find(keyword)
                if pos >= min_pos:  # Keyword должен быть не в начале параграфа
                    # Извлекаем предложения с советами из параграфа
                    sentences = re.split(r'[.!?]', text)
                    for sent in sentences:
                        sent_lower = sent.lower()
                        if any(kw[0] in sent_lower for kw in keywords):
                            cleaned = self.clean_text(sent)
                            if cleaned and 20 < len(cleaned) < 200:
                                notes.append(cleaned)
                    break
        
        # Удаляем дубликаты
        unique_notes = []
        seen = set()
        for note in notes:
            note_norm = note.lower()
            if note_norm not in seen:
                seen.add(note_norm)
                unique_notes.append(note)
        
        return ' '.join(unique_notes) if unique_notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем section с классом tags
        tags_section = self.soup.find('section', class_=lambda x: x and 'tags' in x.lower())
        
        if tags_section:
            # Ищем все ссылки внутри
            links = tags_section.find_all('a')
            for link in links:
                tag_text = self.clean_text(link.get_text())
                if tag_text and len(tag_text) > 2:
                    tags.append(tag_text.lower())
        
        # Если не нашли теги в HTML, проверяем keywords из JSON-LD
        if not tags:
            recipe_data = self._get_recipe_json_ld()
            if recipe_data and 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    tags = [k.strip().lower() for k in keywords.split(',')]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
            elif isinstance(img, str):
                urls.append(img)
        
        # Из meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        return ','.join(urls) if urls else None
    
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки HTML файлов bonviveur.com
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "bonviveur_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BonviveurExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bonviveur_com.py")


if __name__ == "__main__":
    main()
