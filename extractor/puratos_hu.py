"""
Экстрактор данных рецептов для сайта puratos.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PuratosHuExtractor(BaseRecipeExtractor):
    """Экстрактор для puratos.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='p-hero__title')
        if h1:
            # Get text but exclude span with class p-hero__label
            label = h1.find('span', class_='p-hero__label')
            if label:
                label.decompose()
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы типа " recept | Puratos"
            text = re.sub(r'\s+(recept|Puratos).*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
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
        """Извлечение ингредиентов из таблицы"""
        ingredients = []
        
        # Ищем таблицу с ингредиентами
        ing_list = self.soup.find('div', class_='ingredients-list')
        if not ing_list:
            return None
        
        table = ing_list.find('table')
        if not table:
            return None
        
        rows = table.find_all('tr')
        
        # Определяем единицу измерения из заголовка
        default_unit = None
        if rows:
            header_cells = rows[0].find_all(['td', 'th'])
            if len(header_cells) >= 2:
                # Второй столбец обычно содержит единицу измерения
                unit_text = header_cells[1].get_text(strip=True)
                if unit_text and unit_text != '':
                    default_unit = unit_text
        
        for row in rows[1:]:  # Пропускаем заголовок
            cells = row.find_all(['td', 'th'])
            
            # Пропускаем строки-заголовки групп (обычно одна ячейка)
            if len(cells) < 2:
                continue
            
            # Извлекаем название, количество и единицу
            name = cells[0].get_text(strip=True)
            
            # Пропускаем пустые строки или заголовки разделов
            if not name or len(cells) < 2:
                continue
            
            # Если это заголовок секции (например, "Тészta"), пропускаем
            if len(cells) == 1 or (len(cells) >= 2 and not cells[1].get_text(strip=True)):
                continue
            
            amount = None
            unit = default_unit
            
            if len(cells) >= 2:
                amount_text = cells[1].get_text(strip=True)
                if amount_text:
                    amount = amount_text
            
            # Проверяем третий столбец для единицы измерения (если есть)
            if len(cells) >= 3:
                unit_text = cells[2].get_text(strip=True)
                if unit_text:
                    unit = unit_text
            
            # Очищаем данные
            name = self.clean_text(name)
            
            # Добавляем ингредиент
            if name:
                ingredient = {
                    "name": name,
                    "units": unit if unit else None,
                    "amount": int(amount) if amount and amount.isdigit() else amount
                }
                ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с методом приготовления
        method_div = self.soup.find('div', class_='recipe-page__method')
        
        if method_div:
            # Удаляем заголовок "Technológia"
            heading = method_div.find(['h2', 'h3', 'h4'])
            if heading:
                heading.decompose()
            
            # Извлекаем текст
            text = method_div.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            text: Текст инструкций
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        if not text:
            return None
        
        # Паттерны для поиска разных типов времени
        patterns = {
            'prep': [
                r'Pihentessük.*?(\d+)\s*perc',  # Время отдыха теста
                r'pihent.*?(\d+)\s*perc',
            ],
            'cook': [
                r'süssük.*?(\d+[-–]\d+)\s*perc',  # Время выпекания с диапазоном
                r'süssük.*?(\d+)\s*perc',
                r'sütőben.*?(\d+[-–]\d+)\s*perc',
                r'sütőben.*?(\d+)\s*perc',
            ],
            'total': [
                r'tésztaérés\s*(\d+)\s*perc',  # Общее время брожения/созревания теста (приоритет)
                r'kelesszük.*?(\d+)\s*perc',  # Время расстойки (запасной вариант)
            ]
        }
        
        for pattern in patterns.get(time_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        method_div = self.soup.find('div', class_='recipe-page__method')
        if method_div:
            text = method_div.get_text()
            return self.extract_time_from_text(text, 'prep')
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        method_div = self.soup.find('div', class_='recipe-page__method')
        if method_div:
            text = method_div.get_text()
            return self.extract_time_from_text(text, 'cook')
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        method_div = self.soup.find('div', class_='recipe-page__method')
        if method_div:
            text = method_div.get_text()
            return self.extract_time_from_text(text, 'total')
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find(class_=re.compile(r'note|tip|hint', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в метаданных
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags = meta_keywords['content']
            return self.clean_text(tags)
        
        # Ищем в meta tags
        meta_tags = self.soup.find('meta', property='article:tag')
        if meta_tags and meta_tags.get('content'):
            return self.clean_text(meta_tags['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если Recipe напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в контенте страницы
        # Изображение рецепта в hero секции
        hero = self.soup.find('div', class_=re.compile(r'hero|banner', re.I))
        if hero:
            img = hero.find('img')
            if img and img.get('src'):
                src = img['src']
                # Конвертируем относительные URL в абсолютные
                if not src.startswith('http'):
                    src = 'https://www.puratos.hu' + src
                urls.append(src)
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для тестирования парсера"""
    import os
    
    # Обрабатываем папку preprocessed/puratos_hu
    recipes_dir = os.path.join("preprocessed", "puratos_hu")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(PuratosHuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python puratos_hu.py")


if __name__ == "__main__":
    main()
