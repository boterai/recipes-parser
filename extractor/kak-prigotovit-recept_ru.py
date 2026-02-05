"""
Экстрактор данных рецептов для сайта kak-prigotovit-recept.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KakPrigotovitReceptExtractor(BaseRecipeExtractor):
    """Экстрактор для kak-prigotovit-recept.ru"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы
            title_text = re.sub(r'\s*[-–|].*$', '', title_text)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем типичные суффиксы вместе с точкой перед ними
            desc = re.sub(r'\.\s*Заходи.*$', '', desc, flags=re.I)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем первый параграф или blockquote после заголовка
        h1 = self.soup.find('h1')
        if h1:
            # Ищем blockquote (используется для описания на этом сайте)
            post_content = self.soup.find('div', class_='post-content')
            if post_content:
                blockquote = post_content.find('blockquote')
                if blockquote:
                    text = blockquote.get_text(strip=True)
                    if len(text) > 30:
                        return self.clean_text(text)
            
            # Ищем следующий параграф
            next_p = h1.find_next('p')
            if next_p:
                text = next_p.get_text(strip=True)
                # Проверяем, что это не инструкция и не список ингредиентов
                if len(text) > 30 and not text.startswith('Подготовьте'):
                    return self.clean_text(text)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON списка словарей"""
        ingredients = []
        
        # Ищем секцию с заголовком "Ингредиенты"
        ingredients_heading = self.soup.find('h2', string=re.compile(r'Ингредиенты', re.I))
        if not ingredients_heading:
            return None
        
        # Ищем следующий ul после заголовка
        ul = ingredients_heading.find_next('ul')
        if not ul:
            return None
        
        # Извлекаем элементы списка
        items = ul.find_all('li')
        for item in items:
            ingredient_text = item.get_text(strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим ингредиент
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 1/2 чашки свежесваренного кофе"
            
        Returns:
            dict: {"name": "свежесваренный кофе", "amount": "2 1/2", "units": "чашки"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на текстовые
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, text_frac in fraction_map.items():
            text = text.replace(fraction, text_frac)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 1/2 чашки кофе", "1/2 стакана сливок", "200 г муки"
        # Сначала пробуем найти количество с дробью
        pattern = r'^([\d\s/.,]+)?\s*(чашк[иа]|стакан[ао]в?|ст\.?\s*л\.?|ч\.?\s*л\.?|г|кг|мл|л|унци[йя]|фунт[ао]в?|штук[иа]?|шт\.?|больш[иоа]х|среднеего|маленьк[иоа]х|мелкого помола|по желанию|для гарнира|плюс)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        # Убираем запятые в конце
        name = re.sub(r',\s*$', '', name)
        # Убираем фразы "или по вкусу", "по желанию" и т.д.
        name = re.sub(r'\s*(или по вкусу|по вкусу|по желанию|для гарнира|если хотите)\s*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Приводим название к именительному падежу (базовая форма)
        # Убираем окончания родительного падежа для распространенных слов
        name = self._normalize_ingredient_name(name)
        
        if not name or len(name) < 2:
            return None
        
        # Return with keys in the same order as reference
        return {
            "name": name,
            "units": units,  # units before amount
            "amount": amount
        }
    
    def _normalize_ingredient_name(self, name: str) -> str:
        """Приводит название ингредиента к базовой форме (именительный падеж)"""
        # Простая эвристика для распространенных окончаний
        # Родительный падеж -> Именительный падеж
        replacements = {
            r'свежесваренного кофе$': 'свежесваренный кофе',
            r'жирных сливок$': 'жирные сливки',
            r'кофейного ликера,?$': 'кофейный ликер',  # Убираем запятую тоже
            r'водки$': 'водка',
            r'муки$': 'мука',
            r'сахара$': 'сахар',
            r'масла$': 'масло',
            r'сливок$': 'сливки',
            r'яиц$': 'яйца',
        }
        
        for pattern, replacement in replacements.items():
            name = re.sub(pattern, replacement, name, flags=re.I)
        
        return name
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # На этом сайте инструкции находятся в параграфах внутри div.post-content
        # Обычно это длинные параграфы, которые идут после описания и до заголовка "Ингредиенты"
        
        post_content = self.soup.find('div', class_='post-content')
        if not post_content:
            return None
        
        instructions_parts = []
        
        # Получаем все дочерние элементы
        for elem in post_content.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue
            
            # Ищем параграфы
            if elem.name == 'p':
                text = elem.get_text(strip=True)
                text = self.clean_text(text)
                
                # Инструкции обычно длинные (> 50 символов) и не являются вводными фразами
                if (text and len(text) > 50 and 
                    not text.startswith('Подготовьте') and
                    not text.startswith('Этот')):  # Пропускаем описание
                    instructions_parts.append(text)
            
            # Останавливаемся на заголовке "Ингредиенты"
            elif elem.name == 'h2' and re.search(r'Ингредиенты', elem.get_text(), re.I):
                break
        
        if instructions_parts:
            return ' '.join(instructions_parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем теги, определенные теги считаются категорией
        tags = self.extract_tags()
        if tags:
            tags_list = [t.strip() for t in tags.split(',')]
            # Ищем ключевые слова категорий (в нижнем регистре для поиска)
            category_keywords = {
                'десерт': 'Dessert',
                'dessert': 'Dessert',
                'коктейль': 'Коктейль',
                'cocktail': 'Коктейль',
                'пить': 'Коктейль',  # Drink -> Cocktail
                'main': 'Main Course',
                'основное': 'Основное блюдо',
                'суп': 'Суп',
                'soup': 'Soup',
                'салат': 'Салат',
                'salad': 'Salad'
            }
            
            for tag in tags_list:
                tag_lower = tag.lower().strip()
                # Проверяем точные совпадения
                if tag_lower in category_keywords:
                    return category_keywords[tag_lower]
        
        # Если не нашли в тегах, возвращаем None
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из текста инструкций"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем упоминания о времени настаивания/подготовки
        # Примеры: "15-20 минут", "2 часа"
        prep_patterns = [
            r'настояться.*?(\d+[-–]\d+\s*минут)',
            r'настояться.*?(\d+\s*минут)',
            r'дайте.*?остыть.*?(\d+\s*минут)',
        ]
        
        for pattern in prep_patterns:
            match = re.search(pattern, instructions, re.I)
            if match:
                return match.group(1)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем упоминания о времени выпекания/готовки
        # Примеры: "60-70 минут", "45-50 минут"
        cook_patterns = [
            r'Выпекайте.*?(\d+[-–]\d+\s*минут)',
            r'выпекать.*?(\d+[-–]\d+\s*минут)',
            r'готовьте.*?(\d+[-–]\d+\s*минут)',
            r'варите.*?(\d+[-–]\d+\s*минут)',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, instructions, re.I)
            if match:
                return match.group(1)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из текста инструкций"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем упоминания о полном времени (охлаждение, настаивание и т.д.)
        # Примеры: "2 часа", "не менее 1 часа"
        total_patterns = [
            r'минимум на (\d+\s*час[ао]в?)',
            r'не менее (\d+\s*час[ао]в?)',
            r'охладите.*?(\d+\s*час[ао]в?)',
        ]
        
        for pattern in total_patterns:
            match = re.search(pattern, instructions, re.I)
            if match:
                return match.group(1)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы и divs с ключевыми словами
        notes_patterns = [
            r'(Сделайте вперед:.*?)(?=\n|$)',
            r'(пирог можно.*?)(?=\.|$)',
            r'(Держите.*?)(?=\.|$)',
        ]
        
        # Получаем весь текст
        all_text = self.soup.get_text()
        
        # Сначала пробуем найти по паттернам
        for pattern in notes_patterns:
            match = re.search(pattern, all_text, re.I | re.DOTALL)
            if match:
                note = match.group(1)
                note = self.clean_text(note)
                # Убираем переносы строк
                note = re.sub(r'\s+', ' ', note)
                return note
        
        # Ищем текст с "Примечание:"
        note_match = re.search(r'Примечание:\s*([^\.]+\.)', all_text, re.I)
        if note_match:
            note = note_match.group(1)
            note = self.clean_text(note)
            # Capitalize first letter
            if note:
                note = note[0].upper() + note[1:] if len(note) > 1 else note.upper()
            return note
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем ссылки на теги
        # На этом сайте теги обычно в виде ссылок с href содержащим "tags/"
        tag_links = self.soup.find_all('a', href=re.compile(r'/tags/\d+', re.I))
        
        for link in tag_links:
            tag_text = link.get_text(strip=True)
            tag_text = self.clean_text(tag_text).lower()
            # Пропускаем "Тэги" заголовок и пустые теги
            if tag_text and tag_text != 'тэги' and len(tag_text) > 2:
                tags_list.append(tag_text)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в контенте рецепта
        # Обычно изображения рецептов содержат определенные ключевые слова в src
        images = self.soup.find_all('img', src=True)
        for img in images:
            src = img.get('src', '')
            # Ищем изображения, которые выглядят как изображения рецептов
            if any(keyword in src.lower() for keyword in ['upload', 'recipe', 'content', 'wp-content']):
                # Проверяем, что это полный URL или добавляем домен
                if src.startswith('http'):
                    urls.append(src)
                elif src.startswith('/'):
                    urls.append(f'https://kak-prigotovit-recept.ru{src}')
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Обрабатываем папку preprocessed/kak-prigotovit-recept_ru
    preprocessed_dir = os.path.join("preprocessed", "kak-prigotovit-recept_ru")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KakPrigotovitReceptExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kak-prigotovit-recept_ru.py")


if __name__ == "__main__":
    main()
