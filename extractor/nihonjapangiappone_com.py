"""
Экстрактор данных рецептов для сайта nihonjapangiappone.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NihonjapangiapponeExtractor(BaseRecipeExtractor):
    """Экстрактор для nihonjapangiappone.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человекочитаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes" или "X hours"
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
        
        # Конвертируем все в минуты для простого формата
        total_minutes = hours * 60 + minutes
        
        # Возвращаем в простом формате
        if total_minutes >= 60:
            if total_minutes % 60 == 0:
                h = total_minutes // 60
                return f"{h} hour" if h == 1 else f"{h} hours"
            else:
                # Если есть и часы и минуты, возвращаем в минутах
                return f"{total_minutes} minutes"
        elif total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, что это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'name' in json_ld:
            name = json_ld['name']
            # Убираем префиксы типа "Ricetta "
            name = re.sub(r'^Ricetta\s+', '', name, flags=re.IGNORECASE)
            # Убираем описательные части после основного названия
            # Паттерн: извлекаем только первое слово/фразу до описания
            match = re.search(r'^(\w+)', name, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
            return self.clean_text(name)
        
        # Альтернативно из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем "Ricetta " в начале
            title = re.sub(r'^Ricetta\s+', '', title, flags=re.IGNORECASE)
            # Для форматов типа "Insalata di riso nello stile giapponese"
            # берем только основное название до "nello stile"
            match = re.search(r'^(.+?)\s+nello stile', title, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
            
            # Для других форматов - убираем суффиксы
            title = re.sub(r'\s+(Cucina Giapponese).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD name (там есть описание после названия блюда)
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'name' in json_ld:
            name = json_ld['name']
            # Паттерн: "Ricetta X Y" где Y - это описание
            # Например: "Ricetta Chawanmushi zuppa solida di uova con Ginkgo"
            # Нужно извлечь все после названия блюда
            match = re.search(r'^Ricetta\s+(\w+)\s+(.+)$', name, re.IGNORECASE)
            if match:
                # Возвращаем описание с заглавной буквы
                desc = match.group(2)
                return desc[0].upper() + desc[1:] if desc else None
            
            # Если паттерн не подошел, но название есть - используем его как основу
            # Для случаев типа "Ricetta Gomokuni" (без описания в name)
        
        # Пробуем из title (для файлов без JSON-LD)
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем "Ricetta " в начале
            title = re.sub(r'^Ricetta\s+', '', title, flags=re.IGNORECASE)
            # Возвращаем как есть (это и будет описание)
            return self.clean_text(title)
        
        # Fallback на meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Извлекаем основную часть описания из мета
            # Паттерн для gomokuni: "La ricetta del Gomokuni un piatto a base di verdure..."
            match = re.search(r'La ricetta del\s+\w+\s+(.+)', desc, re.IGNORECASE)
            if match:
                # Берем все после названия и возвращаем с заглавной
                full_desc = match.group(1)
                return full_desc[0].upper() + full_desc[1:] if full_desc else None
            
            # Для других форматов
            match = re.search(r',\s+la\s+(.+?),\s+una delle', desc, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
            
            return desc
        
        # Альтернативно из JSON-LD description
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 uova" или "30cc di acqua"
            
        Returns:
            dict: {"name": "uova", "amount": "2", "unit": None}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 uova", "30cc di acqua", "1 cucchiaino di sale", "600 gr. di riso"
        # Сначала ищем количество + единица измерения
        pattern = r'^([\d\s/.,]+)?\s*(cc|gr?\.?|kg|ml|dl|l|cucchiaino|cucchiaini|cucchiaio|cucchiai|tablespoon|tablespoons|teaspoon|teaspoons|pieces?|pezzi?|gambi?)?\s*(?:di\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
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
                amount = int(total) if total == int(total) else total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    val = float(amount_str)
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        # Удаляем точку из единицы измерения (gr. -> gr)
        if unit:
            unit = unit.replace('.', '')
        
        # Очистка названия
        # Удаляем скобки с содержимым (например "(opzionale)" или "(salsa di soia)")
        name = re.sub(r'\s*\([^)]*\)', '', name)
        
        # Удаляем фразы типа "freschi o essiccati" целиком
        name = re.sub(r'\s+(freschi?\s+o\s+essiccati?|essiccati?\s+o\s+freschi?)', '', name, flags=re.IGNORECASE)
        # НЕ удаляем "secchi" когда оно стоит отдельно (это часть описания ингредиента)
        # Удаляем только отдельные прилагательные которые не критичны
        name = re.sub(r'\b(medie?|media|qualche)\b', '', name, flags=re.IGNORECASE)
        # Удаляем оставшиеся "o XXX" в конце только для определенных слов
        name = re.sub(r'\s+o\s+(essiccati?|freschi?)\s*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'^di\s+', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD или HTML"""
        ingredients_list = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Меняем "unit" на "units" для совместимости с форматом из примера
                    ingredients_list.append({
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    })
        else:
            # Если JSON-LD нет, ищем в HTML
            # Ищем секцию с классом "ingredienti"
            ing_section = self.soup.find('font', class_='ingredienti')
            if ing_section:
                items = ing_section.find_all('li')
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients_list.append({
                            "name": parsed["name"],
                            "units": parsed["unit"],
                            "amount": parsed["amount"]
                        })
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Извлекаем из JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            if steps:
                # Объединяем все шаги в одну строку
                return ' '.join(steps)
        
        # Если JSON-LD нет, ищем в HTML
        # Ищем секцию с приготовлением
        justesto_font = self.soup.find('font', class_='justesto')
        if justesto_font:
            items = justesto_font.find_all('li')
            steps = []
            for item in items:
                text = item.get_text(strip=True)
                # Пропускаем заметки о вине и т.д.
                if not text.lower().startswith('vino consigliato'):
                    steps.append(text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Извлекаем из JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                return self.clean_text(json_ld['recipeCategory'])
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                return self.clean_text(json_ld['recipeCuisine'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала ищем в HTML (приоритет, так как там более точные значения)
        # Ищем "Preparazione: XX min"
        prep_div = self.soup.find('div', string=re.compile(r'Preparazione:', re.I))
        if prep_div:
            text = prep_div.get_text(strip=True)
            # Извлекаем числа и единицы
            match = re.search(r'(\d+)\s*(min|hour|ora|ore)', text, re.I)
            if match:
                value = match.group(1)
                unit = match.group(2).lower()
                if 'min' in unit:
                    return f"{value} minutes"
                elif 'hour' in unit or 'ora' in unit or 'ore' in unit:
                    return f"{value} hour" if value == "1" else f"{value} hours"
        
        # Если не нашли в div, ищем в инструкциях упоминание времени
        # Для случаев типа "Mettete in frigo per 20/30 minuti"
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерн "20/30 minuti" или "30 minuti"
            match = re.search(r'(\d+)/(\d+)\s*minuti', instructions, re.I)
            if match:
                # Берем большее значение
                val2 = match.group(2)
                return f"{val2} minutes"
            
            match = re.search(r'(\d+)\s*minuti', instructions, re.I)
            if match:
                return f"{match.group(1)} minutes"
        
        # Fallback на JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала ищем в HTML (приоритет)
        # Ищем "Cottura: XX min"
        cook_div = self.soup.find('div', string=re.compile(r'Cottura:', re.I))
        if cook_div:
            text = cook_div.get_text(strip=True)
            # Извлекаем числа и единицы
            match = re.search(r'(\d+)\s*(min|hour|ora|ore)', text, re.I)
            if match:
                value = match.group(1)
                unit = match.group(2).lower()
                if 'min' in unit:
                    return f"{value} minutes"
                elif 'hour' in unit or 'ora' in unit or 'ore' in unit:
                    return f"{value} hour" if value == "1" else f"{value} hours"
        
        # Fallback на JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Вычисляем из prep + cook (как в референсных данных)
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep or cook:
            # Извлекаем минуты из обоих
            prep_mins = 0
            cook_mins = 0
            
            if prep:
                match = re.search(r'(\d+)\s*(minute|hour)', prep)
                if match:
                    val = int(match.group(1))
                    if 'hour' in match.group(2):
                        prep_mins = val * 60
                    else:
                        prep_mins = val
            
            if cook:
                match = re.search(r'(\d+)\s*(minute|hour)', cook)
                if match:
                    val = int(match.group(1))
                    if 'hour' in match.group(2):
                        cook_mins = val * 60
                    else:
                        cook_mins = val
            
            total_mins = prep_mins + cook_mins
            
            if total_mins >= 60 and total_mins % 60 == 0:
                hours = total_mins // 60
                return f"{hours} hour" if hours == 1 else f"{hours} hours"
            elif total_mins > 0:
                return f"{total_mins} minutes"
        
        # Fallback на JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем в HTML заметки о вине и другие комментарии
        justesto_font = self.soup.find('font', class_='justesto')
        if justesto_font:
            items = justesto_font.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                # Ищем заметки о вине
                if text.lower().startswith('vino consigliato'):
                    return text
        
        # На этом сайте заметки обычно отсутствуют
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем из JSON-LD keywords
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Уже строка с разделителями
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                # Список тегов
                return ', '.join([self.clean_text(k) for k in keywords if k])
        
        # Альтернативно из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        json_ld = self._get_recipe_json_ld()
        if json_ld and 'image' in json_ld:
            image = json_ld['image']
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                urls.extend([img for img in image if isinstance(img, str)])
        
        # Альтернативно из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Убираем дубликаты
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Точка входа для обработки HTML файлов nihonjapangiappone.com"""
    import os
    
    # Обрабатываем папку preprocessed/nihonjapangiappone_com
    preprocessed_dir = os.path.join("preprocessed", "nihonjapangiappone_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NihonjapangiapponeExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python nihonjapangiappone_com.py")


if __name__ == "__main__":
    main()
