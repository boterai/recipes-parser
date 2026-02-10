"""
Экстрактор данных рецептов для сайта kinnusenmylly.fi
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KinnusenmyllyExtractor(BaseRecipeExtractor):
    """Экстрактор для kinnusenmylly.fi"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке статьи
        article = self.soup.find('div', class_='article--ingress')
        if article:
            h1 = article.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        
        # Альтернативно - из заголовка страницы
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффикс " | Kinnusen Mylly"
            title_text = re.sub(r'\s*\|\s*Kinnusen Mylly.*$', '', title_text)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в article--ingress
        ingress = self.soup.find('div', class_='article--ingress')
        if ingress:
            p = ingress.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем таблицу ингредиентов
        table = self.soup.find('section', class_='custom--small--table')
        if not table:
            return None
        
        # Извлекаем строки таблицы
        rows = table.find_all('div', class_='custom--small--table--row')
        
        for row in rows:
            # Пропускаем строки с подзаголовками (sub-title)
            if 'sub--title' in row.get('class', []):
                continue
                
            cols = row.find_all('div', class_='custom--small--table--col')
            if len(cols) >= 2:
                # Первая колонка - количество и единицы
                amount_text = self.clean_text(cols[0].get_text())
                # Вторая колонка - название ингредиента
                name = self.clean_text(cols[1].get_text())
                
                # Парсим количество и единицы
                amount = None
                unit = None
                
                if amount_text:
                    # Обработка дробей вида "1/2 tl"
                    if '/' in amount_text:
                        parts = amount_text.split()
                        if len(parts) >= 2:
                            # "1/2 tl" -> amount="0.5", unit="tl"
                            fraction = parts[0]
                            unit = parts[1] if len(parts) > 1 else None
                            # Вычисляем дробь
                            if '/' in fraction:
                                num, denom = fraction.split('/')
                                amount = str(float(num) / float(denom))
                        else:
                            # Только дробь без единицы
                            num, denom = amount_text.split('/')
                            amount = str(float(num) / float(denom))
                    else:
                        # Обычный паттерн: "2 dl", "1 tl", "1" или "2,5 dl"
                        match = re.match(r'^([\d.,]+)\s*([a-zA-Zäöå]+)?', amount_text)
                        if match:
                            amount = match.group(1).replace(',', '.')
                            unit = match.group(2) if match.group(2) else None
                            
                            # Если есть только число без единиц, используем "pcs"
                            if amount and not unit and not any(c.isalpha() for c in amount_text):
                                unit = "pcs"
                
                # Добавляем ингредиент
                if name:
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": float(amount) if amount and '.' in amount else int(amount) if amount and amount.replace('.', '').isdigit() else None
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем упорядоченный список инструкций
        numbered_list = self.soup.find('div', class_='numbered--list--wrapper')
        if numbered_list:
            ol = numbered_list.find('ol')
            if ol:
                items = ol.find_all('li')
                for item in items:
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        instructions.append(step_text)
        
        # Если не нашли в numbered--list--wrapper, ищем обычный ol
        if not instructions:
            ol = self.soup.find('ol')
            if ol:
                items = ol.find_all('li')
                for item in items:
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        instructions.append(step_text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в breadcrumbs
        breadcrumb = self.soup.find('ol', class_='breadcrumbs')
        if breadcrumb:
            items = breadcrumb.find_all('li')
            if len(items) > 1:
                # Берем предпоследний элемент (последний обычно сам рецепт)
                category_item = items[-2] if len(items) > 2 else items[-1]
                a = category_item.find('a')
                if a:
                    return self.clean_text(a.get_text())
        
        return None
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_label: Метка времени для поиска
        """
        # На этом сайте времени может не быть в HTML структуре
        # Проверяем article для любых меток времени
        article = self.soup.find('article', class_='custom--margin')
        if article:
            text = article.get_text()
            # Ищем паттерны времени (например, "30 minuuttia", "1 tunti")
            patterns = [
                r'(\d+)\s*min(?:uuttia)?',
                r'(\d+)\s*tunti(?:a)?',
                r'(\d+)\s*h'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(0)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return None  # На сайте обычно не указывается отдельно
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания времени
        instructions = self.extract_instructions()
        if instructions:
            # Паттерны для финского языка
            patterns = [
                r'(\d+)\s*minuut(?:tia|in)',
                r'(\d+)\s*tunti(?:a)?',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, instructions, re.IGNORECASE)
                if match:
                    number = match.group(1)
                    if 'tunti' in match.group(0):
                        return f"{int(number) * 60} minutes"
                    else:
                        return f"{number} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None  # На сайте обычно не указывается отдельно
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в article, параграфы с дополнительными заметками
        article = self.soup.find('article', class_='custom--margin')
        if article:
            # Первый параграф обычно заметка/совет
            p = article.find('p')
            if p:
                text = self.clean_text(p.get_text())
                # Проверяем, что это не пустой текст
                if text and len(text) > 10:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # На этом сайте теги обычно отсутствуют в HTML
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем главное изображение рецепта
        product_image = self.soup.find('img', class_='product--image')
        if product_image and product_image.get('src'):
            src = product_image['src']
            # Если URL относительный, добавляем домен
            if src.startswith('/'):
                src = f"https://kinnusenmylly.fi{src}"
            urls.append(src)
        
        # Ищем другие изображения в article
        article = self.soup.find('article')
        if article:
            images = article.find_all('img')
            for img in images:
                if img.get('src'):
                    src = img['src']
                    if src.startswith('/'):
                        src = f"https://kinnusenmylly.fi{src}"
                    if src not in urls:
                        urls.append(src)
        
        # Убираем дубликаты и возвращаем как строку через запятую
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
    import os
    # Обрабатываем папку preprocessed/kinnusenmylly_fi
    recipes_dir = os.path.join("preprocessed", "kinnusenmylly_fi")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KinnusenmyllyExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kinnusenmylly_fi.py")


if __name__ == "__main__":
    main()
