"""
Экстрактор данных рецептов для сайта domacica.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DomacicaComExtractor(BaseRecipeExtractor):
    """Экстрактор для domacica.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT50M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 h 30 min"
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
        
        # Форматируем время
        if hours > 0 and minutes > 0:
            return f"{hours} h {minutes:02d} min"
        elif hours > 0:
            return f"{hours} h 00 min"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в элементе с itemprop="name"
        name_elem = self.soup.find(attrs={'itemprop': 'name'})
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в элементе с itemprop="description"
        desc_elem = self.soup.find(attrs={'itemprop': 'description'})
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: текст ингредиента, например "1 mali luk" или "500 gr krem sira"
            
        Returns:
            Словарь с полями name, amount, units
        """
        ingredient_text = self.clean_text(ingredient_text)
        
        # Инициализация результата
        result = {
            "name": None,
            "units": None,
            "amount": None
        }
        
        if not ingredient_text:
            return result
        
        # Список распознаваемых единиц измерения
        unit_patterns = r'\b(gr|gram|grama|ml|kg|kilogram|l|litar|kašike|kašika|kašičice|kašičica|šolja|šolje|komad|komada|čaša|čaše)\b'
        
        # Паттерны для извлечения количества и единиц измерения
        # Примеры: "500 gr krem sira", "4 kašike putera", "1 komad luka"
        patterns = [
            # Число + единица + название (например: "500 gr krem sira", "4 kašike putera")
            r'^([\d½¼¾⅓⅔⅛⅜⅝⅞.,]+)\s+' + unit_patterns + r'\s+(.+)$',
            # Число + прилагательное + существительное (например: "1 mali luk", "2 velike mrkve")
            # В этом случае прилагательное - часть названия, а единица - "komad"
            r'^([\d½¼¾⅓⅔⅛⅜⅝⅞.,]+)\s+(mali|mala|malo|velike|veliki|veliko|srednji|srednja|srednje)\s+(.+)$',
            # Просто число + название (например: "1 luk", "2 jaja")
            r'^([\d½¼¾⅓⅔⅛⅜⅝⅞.,]+)\s+(.+)$',
        ]
        
        # Попытка извлечь с единицей измерения
        match = re.match(patterns[0], ingredient_text, re.IGNORECASE)
        if match:
            amount_str = match.group(1)
            units = match.group(2)
            name = match.group(3)
            
            # Конвертируем amount в число
            try:
                # Заменяем дробные символы
                amount_str = amount_str.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                amount_str = amount_str.replace('⅓', '0.33').replace('⅔', '0.67')
                amount_str = amount_str.replace(',', '.')
                
                # Пытаемся преобразовать в число
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = amount_str
            
            result["amount"] = amount
            result["units"] = units
            result["name"] = name
            return result
        
        # Попытка с прилагательным (прилагательное идет в название)
        match = re.match(patterns[1], ingredient_text, re.IGNORECASE)
        if match:
            amount_str = match.group(1)
            adjective = match.group(2)
            noun = match.group(3)
            
            # Конвертируем amount в число
            try:
                amount_str = amount_str.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                amount_str = amount_str.replace('⅓', '0.33').replace('⅔', '0.67')
                amount_str = amount_str.replace(',', '.')
                
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = amount_str
            
            result["amount"] = amount
            result["units"] = "komad"  # Подразумеваемая единица для счетных существительных
            result["name"] = f"{adjective} {noun}"  # Прилагательное - часть названия
            return result
        
        # Просто число + название
        match = re.match(patterns[2], ingredient_text, re.IGNORECASE)
        if match:
            amount_str = match.group(1)
            name = match.group(2)
            
            # Конвертируем amount в число
            try:
                amount_str = amount_str.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                amount_str = amount_str.replace('⅓', '0.33').replace('⅔', '0.67')
                amount_str = amount_str.replace(',', '.')
                
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = amount_str
            
            result["amount"] = amount
            result["units"] = "komad"  # Подразумеваемая единица
            result["name"] = name
            return result
        
        # Если не подошел ни один паттерн, возвращаем весь текст как название
        result["name"] = ingredient_text
        return result
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Ищем все элементы с itemprop="ingredients"
        ingredient_items = self.soup.find_all(attrs={'itemprop': 'ingredients'})
        
        if ingredient_items:
            for item in ingredient_items:
                ingredient_text = self.clean_text(item.get_text())
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    ingredients_list.append(parsed)
        
        if not ingredients_list:
            return None
        
        # Возвращаем как JSON строку (как в reference JSON)
        return json.dumps(ingredients_list, ensure_ascii=False)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Ищем элемент с itemprop="recipeInstructions"
        instructions_elem = self.soup.find(attrs={'itemprop': 'recipeInstructions'})
        
        if instructions_elem:
            # Извлекаем все шаги из списка <ol>
            steps = []
            list_items = instructions_elem.find_all('li')
            
            if list_items:
                for item in list_items:
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        steps.append(step_text)
                
                # Объединяем шаги в одну строку
                return ' '.join(steps) if steps else None
            else:
                # Если нет списка, берем весь текст
                text = self.clean_text(instructions_elem.get_text())
                return text if text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в графе данных
                if isinstance(data, dict) and '@graph' in data:
                    graph = data['@graph']
                    for item in graph:
                        if isinstance(item, dict):
                            # Ищем в NewsArticle
                            if item.get('@type') == 'NewsArticle' and 'articleSection' in item:
                                section = item['articleSection']
                                if isinstance(section, list) and section:
                                    return self.clean_text(section[0])
                                elif isinstance(section, str):
                                    return self.clean_text(section)
                            
                            # Ищем в keywords
                            if 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, str):
                                    # Берем первую категорию из keywords
                                    parts = keywords.split(',')
                                    # Пытаемся найти основную категорию (Soup, Dessert, etc.)
                                    for part in parts:
                                        part = part.strip()
                                        # Проверяем на основные категории
                                        if re.search(r'\b(soup|supa|corba|dessert|main|salad)\b', part, re.IGNORECASE):
                                            return self.clean_text(part.capitalize())
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем элемент с itemprop="prepTime"
        prep_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        
        if prep_elem:
            # Проверяем атрибут content (ISO format)
            content = prep_elem.get('content')
            if content:
                return self.parse_iso_duration(content)
            
            # Иначе берем текст элемента
            text = self.clean_text(prep_elem.get_text())
            if text:
                # Форматируем текст (например "20 min" -> "20 minutes")
                text = re.sub(r'\bmin\b', 'minutes', text)
                return text
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем элемент с itemprop="cookTime"
        cook_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        
        if cook_elem:
            # Проверяем атрибут content (ISO format)
            content = cook_elem.get('content')
            if content:
                return self.parse_iso_duration(content)
            
            # Иначе берем текст элемента
            text = self.clean_text(cook_elem.get_text())
            if text:
                # Форматируем текст (например "30 min" -> "30 minutes")
                text = re.sub(r'\bmin\b', 'minutes', text)
                return text
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем элемент с itemprop="totalTime"
        total_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        
        if total_elem:
            # Проверяем атрибут content (ISO format)
            content = total_elem.get('content')
            if content:
                return self.parse_iso_duration(content)
            
            # Иначе берем текст элемента
            text = self.clean_text(total_elem.get_text())
            if text:
                # Форматируем текст (например "50 min" -> "50 minutes")
                text = re.sub(r'\bmin\b', 'minutes', text)
                return text
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/комментариев к рецепту"""
        # Ищем секцию с заметками/советами
        # На domacica.com может не быть отдельной секции для заметок
        notes_patterns = [
            r'note',
            r'tip',
            r'napomena',
            r'savjet'
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=re.compile(pattern, re.I))
            if notes_section:
                text = self.clean_text(notes_section.get_text())
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD или meta"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в графе данных
                if isinstance(data, dict) and '@graph' in data:
                    graph = data['@graph']
                    for item in graph:
                        if isinstance(item, dict) and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, str):
                                # Возвращаем keywords как есть (уже в формате через запятую)
                                return self.clean_text(keywords)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url not in image_urls:
                image_urls.append(url)
        
        # 2. Ищем в itemprop="image"
        image_elems = self.soup.find_all(attrs={'itemprop': 'image'})
        for img_elem in image_elems:
            # Проверяем src атрибут
            src = img_elem.get('src')
            if src and src not in image_urls:
                image_urls.append(src)
            
            # Проверяем srcset (может содержать несколько URL)
            srcset = img_elem.get('srcset')
            if srcset:
                # Парсим srcset (формат: "url1 width1, url2 width2, ...")
                for part in srcset.split(','):
                    url_part = part.strip().split()[0]
                    if url_part and url_part not in image_urls:
                        image_urls.append(url_part)
        
        # 3. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в графе данных
                if isinstance(data, dict) and '@graph' in data:
                    graph = data['@graph']
                    for item in graph:
                        if isinstance(item, dict):
                            # Проверяем поле image
                            if 'image' in item:
                                img_data = item['image']
                                # Может быть объектом с @id или url
                                if isinstance(img_data, dict):
                                    url = img_data.get('url') or img_data.get('@id')
                                    if url and url not in image_urls:
                                        image_urls.append(url)
                                elif isinstance(img_data, str):
                                    if img_data not in image_urls:
                                        image_urls.append(img_data)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        if not image_urls:
            return None
        
        # Возвращаем как строку через запятую (как указано в требованиях)
        return ','.join(image_urls)
    
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
    """
    Основная функция для обработки HTML файлов из директории preprocessed/domacica_com
    """
    import os
    
    # Путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "domacica_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка файлов из: {recipes_dir}")
        process_directory(DomacicaComExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Создайте директорию preprocessed/domacica_com и поместите в нее HTML файлы рецептов")


if __name__ == "__main__":
    main()
