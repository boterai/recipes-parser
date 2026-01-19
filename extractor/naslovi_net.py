"""
Экстрактор данных рецептов для сайта naslovi.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NasloviNetExtractor(BaseRecipeExtractor):
    """Экстрактор для naslovi.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Naslovi.net"
            title = re.sub(r'\s*-\s*Naslovi\.net\s*$', '', title, flags=re.IGNORECASE)
            # Удаляем префиксы типа "Recept za ", "Najbolji recept za ", etc.
            title = re.sub(r'^.*?recept\s+za\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r':\s*.*$', '', title)  # Удаляем все после двоеточия
            return self.clean_text(title)
        
        # Альтернативно - из H1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text()
            title = re.sub(r'^.*?recept\s+za\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r':\s*.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Извлекаем только вводную часть до "Sastojci:" или "Припрема:"
            desc = re.split(r'Sastojci:|Припрема:', desc, flags=re.IGNORECASE)[0]
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.split(r'Sastojci:|Припрема:', desc, flags=re.IGNORECASE)[0]
            return self.clean_text(desc)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из meta description"""
        ingredients = []
        
        # Получаем полный текст из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if not meta_desc or not meta_desc.get('content'):
            meta_desc = self.soup.find('meta', property='og:description')
        
        if not meta_desc or not meta_desc.get('content'):
            return None
        
        desc = meta_desc['content']
        
        # Извлекаем секцию с ингредиентами
        # Ищем текст между "Sastojci:" и "Priprema:" или "Припрема:"
        sastojci_match = re.search(r'Sastojci:\s*(.+?)(?:Priprema:|Припрема:|$)', desc, re.IGNORECASE | re.DOTALL)
        if sastojci_match:
            ingredients_text = sastojci_match.group(1).strip()
        else:
            return None
        
        # Парсим каждый ингредиент
        # Формат: "количество единица_измерения название"
        # Примеры: "300 г брашна", "1 glavica crnog luka", "4 јајета"
        lines = ingredients_text.split('\n')
        text_lines = ' '.join(lines)
        
        # Разделяем по цифрам в начале (новый ингредиент начинается с цифры или слова)
        parts = re.split(r'\s+(?=\d+\s)', text_lines)
        
        for part in parts:
            part = self.clean_text(part)
            if not part or len(part) < 2:
                continue
            
            parsed = self.parse_ingredient_naslovi(part)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_naslovi(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента для naslovi.net
        
        Формат может быть:
        - "1 glavica crnog luka" -> amount: 1, unit: head, name: crni luk
        - "300 г брашна" -> amount: 300, unit: g, name: брашно
        - "4 јајета" -> amount: 4, unit: null, name: јаја
        """
        if not text:
            return None
        
        text = self.clean_text(text).strip()
        
        # Маппинг единиц измерения на английский и нормализация
        unit_map = {
            'g': 'g', 'г': 'g', 'gram': 'g', 'grama': 'g',
            'ml': 'ml', 'мл': 'ml', 'milliliter': 'ml',
            'kg': 'kg', 'кг': 'kg', 'kilogram': 'kg',
            'l': 'l', 'litr': 'l', 'литар': 'l',
            'glavica': 'head', 'главица': 'head',
            'kašika': 'tablespoon', 'kašičica': 'teaspoon', 'кашика': 'tablespoon', 'кашичица': 'teaspoon', 'kašike': 'tablespoons',
            'pakovanje': 'package', 'kесица': 'package', 'kesica': 'package',
            'komad': 'piece', 'kom': 'piece', 'комад': 'piece',
            'prazi': 'piece',  # "prazi luk" - это лук-порей
        }
        
        # Паттерн: количество [единица] название
        # Примеры: "1 glavica crnog luka", "300 г брашна", "4 јајета"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*([a-zа-яёђжзјљњћџšđčćž]+)?\s+(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1)
            unit_str = match.group(2)
            name_str = match.group(3)
            
            # Обработка количества
            amount = amount_str.replace(',', '.')
            try:
                # Пробуем преобразовать в число
                amount_num = float(amount)
                # Если целое число, сохраняем как int
                if amount_num.is_integer():
                    amount = int(amount_num)
                else:
                    amount = amount_num
            except ValueError:
                pass
            
            # Обработка единицы измерения
            unit = None
            if unit_str:
                unit_lower = unit_str.lower()
                unit = unit_map.get(unit_lower, unit_str)
            
            # Очистка названия
            name = self.clean_text(name_str)
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Если не совпал паттерн, пробуем без единицы
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            amount_str = match2.group(1)
            name_str = match2.group(2)
            
            amount = amount_str.replace(',', '.')
            try:
                amount_num = float(amount)
                if amount_num.is_integer():
                    amount = int(amount_num)
                else:
                    amount = amount_num
            except ValueError:
                pass
            
            name = self.clean_text(name_str)
            
            return {
                "name": name,
                "amount": amount,
                "unit": None
            }
        
        # Если не совпал ни один паттерн, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Получаем полный текст из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if not meta_desc or not meta_desc.get('content'):
            meta_desc = self.soup.find('meta', property='og:description')
        
        if not meta_desc or not meta_desc.get('content'):
            return None
        
        desc = meta_desc['content']
        
        # Извлекаем секцию с инструкциями
        # Ищем текст после "Priprema:" или "Припрема:"
        priprema_match = re.search(r'(?:Priprema:|Припрема:)\s*(.+)', desc, re.IGNORECASE | re.DOTALL)
        if priprema_match:
            instructions = priprema_match.group(1).strip()
            return self.clean_text(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Попробуем извлечь из JSON-LD, если есть
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe' and 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'recipeCategory' in item:
                            return self.clean_text(item['recipeCategory'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe' and 'prepTime' in data:
                        return data['prepTime']
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'prepTime' in item:
                            return item['prepTime']
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe' and 'cookTime' in data:
                        return data['cookTime']
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'cookTime' in item:
                            return item['cookTime']
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe' and 'totalTime' in data:
                        return data['totalTime']
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'totalTime' in item:
                            return item['totalTime']
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Для naslovi.net нет отдельной секции с заметками в примерах
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем извлечь из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Пробуем извлечь из JSON-LD
        if not tags:
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if data.get('@type') == 'Recipe' and 'keywords' in data:
                            keywords = data['keywords']
                            if isinstance(keywords, list):
                                tags = keywords
                            elif isinstance(keywords, str):
                                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags = keywords
                                elif isinstance(keywords, str):
                                    tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = [data]
                
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'image' in item:
                        img = item['image']
                        if isinstance(img, str):
                            if img not in urls:
                                urls.append(img)
                        elif isinstance(img, list):
                            for i in img:
                                if isinstance(i, str) and i not in urls:
                                    urls.append(i)
                        elif isinstance(img, dict):
                            if 'url' in img and img['url'] not in urls:
                                urls.append(img['url'])
            except (json.JSONDecodeError, KeyError):
                continue
        
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки preprocessed/naslovi_net"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "naslovi_net")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(NasloviNetExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python naslovi_net.py")


if __name__ == "__main__":
    main()
