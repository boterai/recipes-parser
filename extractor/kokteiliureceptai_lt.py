"""
Экстрактор данных рецептов для сайта kokteiliureceptai.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KokteiliureceptaiLtExtractor(BaseRecipeExtractor):
    """Экстрактор для kokteiliureceptai.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Извлекаем из h1 с itemprop="name"
        h1 = self.soup.find('h1', itemprop='name')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - любой h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем префикс "Kokteilis / "
            if '/' in title_text:
                return self.clean_text(title_text.split('/')[-1].strip())
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Описание может быть в div.basic-drink
        basic_drink = self.soup.find('div', class_='basic-drink')
        if basic_drink:
            text = self.clean_text(basic_drink.get_text())
            if text:
                return text
        
        return None
    
    def parse_ingredient_amount(self, amount_text: str) -> tuple:
        """
        Парсинг количества ингредиента
        
        Args:
            amount_text: Строка вида "30 ml" или "2 arbat. šaukštel." или "pagal skonį"
            
        Returns:
            tuple: (amount, unit)
        """
        if not amount_text:
            return (None, None)
        
        text = self.clean_text(amount_text).strip()
        
        # Если "pagal skonį" или подобное - то amount=null, unit=весь текст
        if not re.search(r'\d', text):
            return (None, text)
        
        # Регулярка для извлечения числа и единицы измерения
        match = re.match(r'^([\d.,/]+)\s*(.*)$', text)
        if match:
            amount = match.group(1)
            unit = match.group(2).strip()
            return (amount, unit if unit else None)
        
        return (None, text)
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем dl с itemprop="ingredient"
        ingredient_list = self.soup.find('dl', itemprop='ingredient')
        if ingredient_list:
            # Извлекаем пары dt (name) и dd (amount)
            names = ingredient_list.find_all('dt', itemprop='name')
            amounts = ingredient_list.find_all('dd', itemprop='amount')
            
            for i in range(len(names)):
                name = self.clean_text(names[i].get_text())
                amount_text = self.clean_text(amounts[i].get_text()) if i < len(amounts) else ""
                
                # Парсим количество и единицу измерения
                amount, unit = self.parse_ingredient_amount(amount_text)
                
                ingredients.append({
                    "name": name,
                    "units": unit,
                    "amount": amount
                })
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем ordered list после заголовка "PARUOŠIMAS:"
        # Инструкции находятся в <ol> после <h2> с текстом "PARUOŠIMAS:"
        ol_lists = self.soup.find_all('ol')
        
        for ol in ol_lists:
            # Проверяем, что перед этим списком есть h2 с текстом PARUOŠIMAS
            prev_sibling = ol.find_previous_sibling()
            if prev_sibling and 'PARUOŠIMAS' in prev_sibling.get_text():
                # Извлекаем все li элементы
                items = ol.find_all('li')
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text:
                        instructions.append(text)
                break
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория может быть в div.head с текстом "ALKOHOLINIAI GĖRIMAI:"
        head_divs = self.soup.find_all('div', class_='head')
        for div in head_divs:
            text = div.get_text()
            if 'GĖRIMAI' in text or 'ALKOHOL' in text:
                # Убираем двоеточие в конце
                category = self.clean_text(text.rstrip(':'))
                return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте времени подготовки нет в HTML
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # На этом сайте времени готовки нет в HTML
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте общего времени нет в HTML
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Заметки находятся в секции после заголовка "PATARIMAS / INFO"
        # Ищем h2 с классом header и текстом "PATARIMAS"
        headers = self.soup.find_all('h2', class_='header')
        
        for header in headers:
            if 'PATARIMAS' in header.get_text():
                # Следующий элемент после заголовка - это p с заметками
                next_p = header.find_next_sibling('p')
                if next_p:
                    text = self.clean_text(next_p.get_text())
                    if text:
                        # Берем только первое предложение
                        sentences = re.split(r'(?<=[.!?])\s+', text)
                        if sentences:
                            return sentences[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Теги могут быть в мета-тегах keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = self.clean_text(meta_keywords['content'])
            return keywords
        
        # Альтернативно, формируем теги из категории и названия
        tags_list = []
        
        # Добавляем "kokteilis" как базовый тег для всех рецептов
        tags_list.append('kokteilis')
        
        # Добавляем категорию если есть
        category = self.extract_category()
        if category:
            if 'ALKOHOL' in category.upper():
                tags_list.append('alkoholis')
        
        # Добавляем название блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            tags_list.append(dish_name)
        
        if tags_list:
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Основное изображение с itemprop="photo"
        main_img = self.soup.find('img', itemprop='photo')
        if main_img and main_img.get('src'):
            src = main_img['src']
            # Преобразуем относительный URL в абсолютный
            if src.startswith('/'):
                src = 'https://kokteiliureceptai.lt' + src
            urls.append(src)
        
        # Убираем дубликаты
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки директории с HTML-файлами"""
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "kokteiliureceptai_lt"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KokteiliureceptaiLtExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kokteiliureceptai_lt.py")


if __name__ == "__main__":
    main()
