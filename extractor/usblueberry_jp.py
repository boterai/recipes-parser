"""
Экстрактор данных рецептов для сайта usblueberry.jp
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class UsblueberryJpExtractor(BaseRecipeExtractor):
    """Экстрактор для usblueberry.jp"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в title теге
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы типа " | USハイブッシュブルーベリー協会"
            title_text = re.sub(r'\s*[|｜].*$', '', title_text)
            return self.clean_text(title_text)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content']
            title_text = re.sub(r'\s*[|｜].*$', '', title_text)
            return self.clean_text(title_text)
        
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
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find('div', class_='ingredients')
        if not ingredients_container:
            return None
        
        # Извлекаем список ингредиентов
        items = ingredients_container.find_all('li')
        
        for item in items:
            # Ищем название и количество
            name_elem = item.find('div', class_='ingredient_name')
            quantity_elem = item.find('div', class_='quantity')
            
            if not name_elem:
                continue
            
            name = self.clean_text(name_elem.get_text())
            
            # Пропускаем заголовки секций:
            # - Начинаются с угловых скобок 〈 или ＜
            # - Содержат "材料" (ингредиенты) или заканчиваются на "〉" или "＞"
            if (name.startswith('〈') or name.startswith('＜') or 
                name.endswith('〉') or name.endswith('＞') or
                '材料' in name):
                continue
            
            # Извлекаем количество
            quantity = None
            if quantity_elem:
                quantity_text = self.clean_text(quantity_elem.get_text())
                # Удаляем точки в начале (..... или .....)
                quantity_text = re.sub(r'^\.+\s*', '', quantity_text)
                # Удаляем примечания в скобках и комментарии
                quantity_text = re.sub(r'※.*$', '', quantity_text)
                quantity_text = re.sub(r'\(.*?\)', '', quantity_text)
                quantity_text = quantity_text.strip()
                quantity = quantity_text if quantity_text else None
            
            # Парсим ингредиент
            parsed = self.parse_ingredient(name, quantity)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, name: str, quantity: Optional[str]) -> Optional[dict]:
        """
        Парсинг ингредиента в структурированный формат
        
        Args:
            name: Название ингредиента
            quantity: Строка с количеством и единицами (например, "280g", "4個", "大さじ1")
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not name:
            return None
        
        # Очищаем название от комментариев в скобках
        name = re.sub(r'[（(].*?[）)]', '', name)
        name = self.clean_text(name).strip()
        
        if not name:
            return None
        
        amount = None
        unit = None
        
        if quantity:
            # Паттерны для извлечения количества и единиц
            # Примеры: "280g", "4個", "大さじ1", "小さじ1/2", "適量"
            
            # Если только "適量" или подобное - без конкретного количества
            if re.match(r'^適量$|^少々$', quantity):
                unit = quantity
                amount = None
            else:
                # Сначала проверяем паттерны с единицами в начале (大さじ1, 小さじ1/2)
                unit_first_match = re.match(r'^(大さじ|小さじ|カップ)[\s]*(\d+(?:/\d+)?)', quantity)
                
                if unit_first_match:
                    unit = unit_first_match.group(1)
                    amount_str = unit_first_match.group(2)
                    
                    # Обрабатываем дробь (например, "1/2")
                    if '/' in amount_str:
                        parts = amount_str.split('/')
                        if len(parts) == 2:
                            try:
                                amount = float(parts[0]) / float(parts[1])
                            except (ValueError, ZeroDivisionError):
                                amount = amount_str
                    else:
                        try:
                            # Пытаемся конвертировать в число
                            if '.' in amount_str:
                                amount = float(amount_str)
                            else:
                                amount = int(amount_str)
                        except ValueError:
                            amount = amount_str
                else:
                    # Извлекаем число (может быть дробь или десятичное)
                    number_match = re.search(r'([\d]+\.?[\d]*|[\d]*/[\d]+)', quantity)
                    
                    if number_match:
                        amount_str = number_match.group(1)
                        
                        # Обрабатываем дробь (например, "1/2")
                        if '/' in amount_str:
                            parts = amount_str.split('/')
                            if len(parts) == 2:
                                try:
                                    amount = float(parts[0]) / float(parts[1])
                                except (ValueError, ZeroDivisionError):
                                    amount = amount_str
                        else:
                            try:
                                # Пытаемся конвертировать в число
                                if '.' in amount_str:
                                    amount = float(amount_str)
                                else:
                                    amount = int(amount_str)
                            except ValueError:
                                amount = amount_str
                        
                        # Извлекаем единицу измерения (все, что после числа)
                        unit_text = quantity[number_match.end():].strip()
                        if unit_text:
                            unit = unit_text
                    else:
                        # Если число не найдено, возможно это просто единица
                        unit = quantity
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с методом приготовления
        method_container = self.soup.find('div', class_='method')
        if not method_container:
            return None
        
        # Извлекаем шаги из списка
        step_items = method_container.find_all('li')
        
        for item in step_items:
            step_text = item.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            
            if step_text:
                # Убираем номера в начале типа "①", "②" и т.д.
                step_text = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]+\s*', '', step_text)
                # Убираем также римские цифры с кружками в начале
                step_text = re.sub(r'^[③⑥⑦⑩]+\s*', '', step_text)
                steps.append(step_text)
        
        if steps:
            # Объединяем все шаги в одну строку с точками в конце каждого шага
            result = '。'.join(steps)
            # Если последний шаг не заканчивается на точку, добавляем её
            if not result.endswith('。'):
                result += '。'
            return result
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пытаемся извлечь из хлебных крошек (breadcrumbs)
        # Ищем в JSON-LD схеме
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Если это объект с @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем последний элемент перед текущей страницей
                            if len(items) >= 2:
                                # Предпоследний элемент - это категория
                                category = items[-2].get('name')
                                if category and category != 'ホーム':
                                    return self.clean_text(category)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте обычно не разделяют prep и cook time
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания времени
        method_container = self.soup.find('div', class_='method')
        if not method_container:
            return None
        
        method_text = method_container.get_text()
        
        # Паттерны для времени: "約25分", "25分", "10分"
        time_match = re.search(r'約?\s*(\d+)\s*分', method_text)
        if time_match:
            minutes = time_match.group(1)
            return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно не указывается отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На этом сайте обычно нет секции с заметками
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем контейнер с тегами
        tag_container = self.soup.find('div', class_='tag')
        if tag_container:
            tag_links = tag_container.find_all('a')
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text:
                    tags_list.append(tag_text)
        
        if tags_list:
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Обрабатываем различные структуры
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'WebPage' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
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
    """
    Точка входа для обработки HTML-файлов из директории preprocessed/usblueberry_jp
    """
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join("preprocessed", "usblueberry_jp")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(UsblueberryJpExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python usblueberry_jp.py")


if __name__ == "__main__":
    main()
