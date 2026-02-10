"""
Экстрактор данных рецептов для сайта kokteiline.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KokteilineLtExtractor(BaseRecipeExtractor):
    """Экстрактор для kokteiline.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Убираем суффикс " - Kokteilinė"
            title = re.sub(r'\s*-\s*Kokteilinė\s*$', '', title, flags=re.IGNORECASE)
            if title:
                return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Kokteilinė"
            title = re.sub(r'\s*-\s*Kokteilinė\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из хлебных крошек
        breadcrumb = self.soup.find(class_='qodef-breadcrumbs-current')
        if breadcrumb:
            return self.clean_text(breadcrumb.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в секции ингредиентов - первый параграф с описанием
        ingredients_section = self.soup.find('div', class_=lambda x: x and 'recipe-ingredients' in x)
        if ingredients_section:
            # Первый параграф часто содержит описание
            first_p = ingredients_section.find('p', class_='qodef-m-description')
            if first_p:
                description = first_p.get_text(strip=True)
                if description:
                    return self.clean_text(description)
        
        # Альтернативно - из meta description (может содержать весь рецепт)
        # Пытаемся извлечь только описание из начала
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            full_desc = og_desc['content']
            # Извлекаем текст до слова "Ingredientai"
            match = re.search(r'^(.+?)\s+Ingredientai', full_desc, re.IGNORECASE)
            if match:
                desc = match.group(1)
                # Убираем название рецепта из начала
                dish_name = self.extract_dish_name()
                if dish_name:
                    desc = re.sub(r'^' + re.escape(dish_name) + r'\s*', '', desc, flags=re.IGNORECASE)
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "Degtinė 60 ml" или "Ananaso skiltelė"
            
        Returns:
            dict: {"name": "Degtinė", "amount": "60", "unit": "ml"} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text)
        
        # Паттерн для извлечения: название + количество + единица
        # Примеры: "Degtinė 60 ml", "Aviečių likeris 15 ml"
        # Формат: <название> <количество> <единица>
        pattern = r'^(.+?)\s+([\d.,]+)\s+([a-zA-Zčšžąęėįųūė]+)$'
        
        match = re.match(pattern, text)
        
        if match:
            name, amount, unit = match.groups()
            return {
                "name": self.clean_text(name),
                "amount": amount.replace(',', '.'),
                "unit": self.clean_text(unit)
            }
        
        # Если паттерн не совпал (например, "Ananaso skiltelė" без количества)
        # Возвращаем только название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами
        ingredients_section = self.soup.find('div', class_=lambda x: x and 'recipe-ingredients' in x)
        
        if not ingredients_section:
            return None
        
        # Находим все параграфы
        paragraphs = ingredients_section.find_all('p')
        
        for p in paragraphs:
            # Получаем текст
            text = p.get_text(separator=' ', strip=True)
            
            # Пропускаем описание рецепта (обычно первый параграф с классом qodef-m-description)
            if 'qodef-m-description' in p.get('class', []):
                continue
            
            # Пропускаем длинные тексты (вероятно инструкции)
            if len(text) > 100:
                continue
            
            # Пропускаем заголовки (заканчиваются на ':')
            if text.endswith(':'):
                continue
            
            # Парсим ингредиент
            if text:
                parsed = self.parse_ingredient_line(text)
                if parsed:
                    ingredients.append(parsed)
        
        # Фильтруем ингредиенты - убираем те, что похожи на инструкции
        # (содержат слова типа "supilkite", "nukoškite" и т.д.)
        instruction_keywords = ['supilkite', 'nukoškite', 'papuoškite', 'suplakite', 
                                'išmaišykite', 'pripildykite', 'sutarkuodami']
        
        filtered_ingredients = []
        for ing in ingredients:
            name_lower = ing['name'].lower()
            is_instruction = any(keyword in name_lower for keyword in instruction_keywords)
            if not is_instruction:
                filtered_ingredients.append(ing)
        
        return json.dumps(filtered_ingredients, ensure_ascii=False) if filtered_ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем инструкции в div с классом icon_with_text
        instruction_divs = self.soup.find_all('div', class_=lambda x: x and 'icon_with_text' in x)
        
        for div in instruction_divs:
            # Ищем параграф с текстом инструкции
            p = div.find('p', class_='qodef-m-text')
            if p:
                text = p.get_text(strip=True)
                text = self.clean_text(text)
                if text:
                    steps.append(text)
        
        # Если не нашли через icon_with_text, пробуем искать в секции ингредиентов
        # (иногда инструкции могут быть там же)
        if not steps:
            ingredients_section = self.soup.find('div', class_=lambda x: x and 'recipe-ingredients' in x)
            if ingredients_section:
                paragraphs = ingredients_section.find_all('p')
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    # Инструкции обычно длинные и содержат глаголы
                    if len(text) > 50 and ('supilkite' in text.lower() or 
                                           'nukoškite' in text.lower() or 
                                           'papuoškite' in text.lower() or
                                           'suplakite' in text.lower()):
                        text = self.clean_text(text)
                        if text not in steps:
                            steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('div', class_=lambda x: x and 'breadcrumbs' in x)
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем категорию перед самим рецептом (обычно предпоследняя ссылка)
            if len(links) > 1:
                # Пропускаем "Home" и берем следующую категорию
                for link in links[1:]:
                    text = link.get_text(strip=True)
                    if text and text.lower() not in ['home', 'pradžia']:
                        return self.clean_text(text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # kokteiline.lt не имеет отдельного времени подготовки в примерах
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # kokteiline.lt не имеет времени приготовления в примерах
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # kokteiline.lt не имеет общего времени в примерах
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # kokteiline.lt не имеет секции с заметками в примерах
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в meta
        keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            tags_string = keywords_meta['content']
            # Разделяем по запятым и очищаем
            tags_list = [self.clean_text(tag) for tag in tags_string.split(',') if tag.strip()]
            return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Проверяем, что это не логотип или SVG
            if not url.endswith('.svg') and 'logo' not in url.lower():
                urls.append(url)
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if not url.endswith('.svg') and 'logo' not in url.lower():
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обрабатываем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                url = item['url']
                                if not url.endswith('.svg') and 'logo' not in url.lower():
                                    urls.append(url)
                            elif 'contentUrl' in item:
                                url = item['contentUrl']
                                if not url.endswith('.svg') and 'logo' not in url.lower():
                                    urls.append(url)
            
            except (json.JSONDecodeError, KeyError, TypeError):
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
    import os
    # Обрабатываем папку preprocessed/kokteiline_lt
    recipes_dir = os.path.join("preprocessed", "kokteiline_lt")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KokteilineLtExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kokteiline_lt.py")


if __name__ == "__main__":
    main()
