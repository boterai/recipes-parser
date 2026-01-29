"""
Экстрактор данных рецептов для сайта receptmuves.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptmuvesHuExtractor(BaseRecipeExtractor):
    """Экстрактор для receptmuves.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h2', class_='post-title entry-title')
        if recipe_header:
            # Извлекаем текст из ссылки внутри заголовка
            link = recipe_header.find('a')
            if link:
                return self.clean_text(link.get_text())
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " ~ Receptműves"
            title = re.sub(r'\s*~\s*Receptműves.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в теле поста
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if post_body:
            first_p = post_body.find('p')
            if first_p:
                text = first_p.get_text(strip=True)
                # Убираем части, которые не являются описанием
                # Например "ÍR SZÓDÁS KENYÉR 2 személyre" не является описанием
                if 'KENYÉR' not in text.upper() and 'személyre' not in text:
                    # Убираем многоточие в конце если есть
                    text = re.sub(r'\.\.\.+$', '.', text)
                    return self.clean_text(text)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "125 g finomliszt" или "1 csapott teáskanál szódabikarbóna"
            
        Returns:
            dict: {"name": "finomliszt", "amount": 125, "unit": "g"} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "125 g finomliszt", "1 csapott teáskanál szódabikarbóna", "200 ml víz"
        # Поддерживаем различные единицы измерения на венгерском
        units_pattern = r'(?:g|ml|l|kg|dkg|teáskanál|evőkanál|csapott teáskanál|púpozott teáskanál|csészé?|kanál|csepp|csomag|db|darab|gerezd|szem|csipet)'
        
        # Паттерн: [количество] [единица] [название]
        pattern = rf'^([\d,./]+)\s*({units_pattern})\s+(.+?)(?:\s*\([^)]*\))?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount_str = amount_str.replace(',', '.')
            try:
                # Пытаемся преобразовать в число
                if '/' in amount_str:
                    # Обработка дробей типа "1/2"
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        numerator = float(parts[0])
                        denominator = float(parts[1])
                        if denominator != 0:
                            amount = numerator / denominator
                        else:
                            # Некорректная дробь, используем как строку
                            amount = amount_str
                    else:
                        amount = amount_str
                else:
                    amount = float(amount_str)
                # Преобразуем обратно в int если это целое число
                if isinstance(amount, float) and amount == int(amount):
                    amount = int(amount)
            except (ValueError, ZeroDivisionError):
                amount = amount_str
            
            # Очистка названия от скобок и дополнительных примечаний
            name = re.sub(r'\([^)]*\)', '', name)
            name = self.clean_text(name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit.strip()
            }
        
        # Если паттерн не совпал, возвращаем только название
        # Убираем скобки
        name = re.sub(r'\([^)]*\)', '', text)
        name = self.clean_text(name).strip()
        
        if name and len(name) > 1:
            return {
                "name": name,
                "amount": None,
                "unit": None
            }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все параграфы в теле поста
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if not post_body:
            return None
        
        paragraphs = post_body.find_all('p')
        
        # Флаг для определения, когда начались ингредиенты
        ingredients_started = False
        instructions_started = False
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            text = self.clean_text(text)
            
            if not text or text == '&nbsp;':
                continue
            
            # Пропускаем описание и заголовок с количеством порций
            if not ingredients_started:
                # Ингредиенты начинаются после строки типа "ÍR SZÓDÁS KENYÉR 2 személyre"
                if 'személyre' in text.lower() or any(word in text.upper() for word in ['KENYÉR', 'RECEPT', 'ÉTEL']):
                    ingredients_started = True
                    continue
                continue
            
            # Ингредиенты заканчиваются когда начинаются инструкции (номерованные шаги)
            if re.match(r'^\d+\.', text):
                instructions_started = True
                break
            
            # Если это пустой параграф или &nbsp;, пропускаем
            if not text or len(text) < 3:
                continue
            
            # Парсим ингредиент
            ingredient = self.parse_ingredient_line(text)
            if ingredient:
                ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Ищем все параграфы в теле поста
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if not post_body:
            return None
        
        paragraphs = post_body.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            text = self.clean_text(text)
            
            if not text:
                continue
            
            # Проверяем, начинается ли с номера шага
            if re.match(r'^\d+\.', text):
                # Это шаг инструкции
                # Убираем условные примечания в скобках (начинающиеся с "ha" = "if")
                # но оставляем короткие пояснения (списки ингредиентов, описания)
                text = re.sub(r'\s*\(ha [^)]*\)', '', text)
                # Убеждаемся что заканчивается точкой
                if not text.endswith('.'):
                    text = text + '.'
                steps.append(text)
            elif steps:
                # Если мы уже начали собирать шаги, но встретили не-номерованный параграф
                # это может быть секция "Praktikák" или другие примечания
                if 'praktikák' in text.lower() or text.startswith('-'):
                    # Закончились инструкции
                    break
        
        if steps:
            # Объединяем шаги в одну строку с пробелами между ними
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в тегах/меток - обычно первая метка является категорией
        # Ищем текст "Címkék:" (Метки:) и следующие за ним ссылки
        
        # Способ 1: поиск в HTML по тексту "Címkék:"
        body_text = self.soup.get_text()
        if 'Címkék:' in body_text:
            # Ищем все ссылки с rel="tag"
            tag_links = self.soup.find_all('a', rel='tag')
            if tag_links:
                # Часто категория это более общий тег, например "Kenyér"
                for link in tag_links:
                    tag_text = link.get_text(strip=True)
                    # Ищем теги, которые похожи на категории (содержат "Kenyér", "Leves" и т.д.)
                    if any(cat in tag_text for cat in ['Kenyér', 'Leves', 'Főétel', 'Desszert', 'Saláta', 'Sütemény']):
                        return self.clean_text(tag_text)
        
        # Если не нашли точную категорию, попробуем определить по названию блюда или тегам
        dish_name = self.extract_dish_name()
        if dish_name:
            # Если в названии есть "kenyér", категория - "Kenyér"
            if 'kenyér' in dish_name.lower():
                return 'Kenyér(féle)'
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в инструкциях упоминания времени
        # Например: "20-25 perc alatt"
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if not post_body:
            return None
        
        # Ищем в параграфах с номерованными шагами
        paragraphs = post_body.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Проверяем что это шаг инструкции
            if re.match(r'^\d+\.', text):
                # Ищем паттерн времени в минутах
                time_pattern = r'(\d+-\d+|\d+)\s*perc'
                match = re.search(time_pattern, text, re.IGNORECASE)
                if match:
                    time_str = match.group(1)
                    return f"{time_str} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Обычно не указывается явно на этом сайте
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно не указывается явно на этом сайте
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию "Praktikák:" (Советы/Практики)
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if not post_body:
            return None
        
        paragraphs = post_body.find_all('p')
        
        notes_started = False
        notes = []
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            text = self.clean_text(text)
            
            if not text:
                continue
            
            # Ищем заголовок "Praktikák:"
            if 'praktikák:' in text.lower():
                notes_started = True
                continue
            
            # Если начались заметки, собираем их
            if notes_started:
                # Заметки часто начинаются с "-"
                if text.startswith('-'):
                    # Убираем начальный "-" и добавляем
                    note_text = text.lstrip('-').strip()
                    # Убираем завершающую запятую если есть
                    note_text = note_text.rstrip(',')
                    # Убеждаемся что заканчивается точкой
                    if not note_text.endswith('.'):
                        note_text = note_text + '.'
                    # Делаем первую букву заглавной
                    if note_text:
                        note_text = note_text[0].upper() + note_text[1:] if len(note_text) > 1 else note_text.upper()
                    notes.append(note_text)
                elif not text.startswith('-') and len(notes) > 0:
                    # Если встретили параграф без "-" после того как начали собирать заметки,
                    # возможно это уже конец заметок
                    # Но продолжаем проверять
                    if any(word in text.lower() for word in ['webshop', 'love2smile', 'http']):
                        # Это реклама или ссылки, пропускаем
                        break
                    # Иначе добавляем как продолжение заметок
                    notes.append(text)
        
        if notes:
            # Берем только первую заметку, как в примере
            return notes[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем все ссылки с rel="tag"
        tag_links = self.soup.find_all('a', rel='tag')
        
        if tag_links:
            tags = []
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text and len(tag_text) > 1:
                    tags.append(tag_text)
            
            if tags:
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в теле поста
        post_body = self.soup.find('div', attrs={'class': lambda x: x and 'post-body' in x and 'entry-content' in x})
        if post_body:
            # Ищем изображения в div с классом "separator"
            separators = post_body.find_all('div', class_='separator')
            for sep in separators:
                img = sep.find('img')
                if img and img.get('src'):
                    # Берем src изображения
                    img_url = img['src']
                    # Также проверяем ссылку-обертку для полноразмерного изображения
                    link = sep.find('a')
                    if link and link.get('href'):
                        # Используем href для полноразмерного изображения
                        img_url = link['href']
                    
                    if img_url not in urls:
                        urls.append(img_url)
            
            # Также ищем все изображения в теле
            all_imgs = post_body.find_all('img')
            for img in all_imgs:
                if img.get('src'):
                    img_url = img['src']
                    # Пропускаем маленькие иконки и превью
                    if 's72-c' not in img_url and img_url not in urls:
                        urls.append(img_url)
        
        # 3. Убираем дубликаты
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Нормализуем URL - используем самое большое разрешение
                # Заменяем /s320/ на /s3968/ или другое большое разрешение
                url_normalized = re.sub(r'/s\d+/', '/s3968/', url)
                if url_normalized not in seen:
                    seen.add(url_normalized)
                    unique_urls.append(url_normalized)
            
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
    import os
    # По умолчанию обрабатываем папку preprocessed/receptmuves_hu
    recipes_dir = os.path.join("preprocessed", "receptmuves_hu")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReceptmuvesHuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python receptmuves_hu.py")


if __name__ == "__main__":
    main()
