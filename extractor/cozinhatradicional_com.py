"""
Экстрактор данных рецептов для сайта cozinhatradicional.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CozinhaTradicionalExtractor(BaseRecipeExtractor):
    """Экстрактор для cozinhatradicional.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта с классом wprm-fallback-recipe-name
        recipe_header = self.soup.find('h2', class_='wprm-fallback-recipe-name')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из основного заголовка страницы
        main_header = self.soup.find('h1', class_='title entry-title')
        if main_header:
            return self.clean_text(main_header.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
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
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 pacote de massa para lasanha" или "500 ml de leite"
            
        Returns:
            dict: {"name": "massa para lasanha", "amount": "1", "units": "pacote"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Убираем скобочные пояснения для упрощения парсинга
        text_for_parsing = re.sub(r'\([^)]*\)', '', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 pacote de massa", "500 ml de leite", "2 colheres de sopa de azeite"
        # Базовые единицы измерения
        units_pattern = r'(?:pacotes?|latas?|unidades?|dentes?|colheres?(?:\s+de\s+sopa)?(?:\s+de\s+chá)?|ml|g|kg|litros?|l|a gosto)'
        
        # Паттерн: число + единица + de + название
        pattern = rf'^(\d+(?:[.,]\d+)?)\s+({units_pattern})\s+(?:de\s+)?(.+)'
        match = re.match(pattern, text_for_parsing.strip(), re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            amount = amount_str.replace(',', '.')
            
            # Очистка названия от "a gosto" и подобных фраз
            name = re.sub(r'\s+(a gosto|quanto baste)$', '', name, flags=re.IGNORECASE).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.strip()
            }
        
        # Паттерн без единицы измерения (только количество + название)
        # Например: "2 cebolas", "3 ovos"
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(.+)'
        match2 = re.match(pattern2, text_for_parsing.strip())
        
        if match2:
            amount_str, name = match2.groups()
            amount = amount_str.replace(',', '.')
            
            # Очистка названия
            name = re.sub(r'\s+(a gosto|quanto baste)$', '', name, flags=re.IGNORECASE).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если нет количества (например, "sal a gosto")
        # Убираем "a gosto", "quanto baste" и т.п.
        name = re.sub(r'\s+(a gosto|quanto baste)$', '', text_for_parsing, flags=re.IGNORECASE).strip()
        
        # Убираем артикли и предлоги в начале
        name = re.sub(r'^(?:o|a|os|as|de|do|da|dos|das)\s+', '', name).strip()
        
        if name and len(name) > 2:
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find('div', class_='wprm-fallback-recipe-ingredients')
        
        if ingredients_container:
            # Извлекаем элементы списка (ul > li)
            items = ingredients_container.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_container = self.soup.find('div', class_='wprm-fallback-recipe-instructions')
        
        if instructions_container:
            # Извлекаем элементы списка (ol > li)
            step_items = instructions_container.find_all('li')
            
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Пропускаем заголовки секций (обычно короткие и заканчиваются двоеточием)
                    # но сохраняем их, если это единственный текст в шаге
                    steps.append(step_text)
        
        # Объединяем все шаги, добавляя нумерацию если её нет
        if steps:
            # Проверяем, есть ли уже нумерация
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в wprm-fallback-recipe-meta-course
        course_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-course')
        if course_meta:
            text = self.clean_text(course_meta.get_text())
            if text:
                # Может содержать несколько значений через запятую
                # Берем последнее значение, которое обычно является основной категорией
                parts = [p.strip() for p in text.split(',') if p.strip()]
                if parts:
                    # Ищем "Prato Principal" или подобные
                    for part in reversed(parts):
                        if any(word in part.lower() for word in ['prato', 'course', 'main', 'principal']):
                            return part
                    # Если не нашли специфичную категорию, возвращаем последнюю
                    return parts[-1]
        
        # Альтернативно - из meta articleSection
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return self.clean_text(article_section['content'])
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в мета-данных рецепта
        cook_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-cook-time')
        if cook_time_meta:
            return self.clean_text(cook_time_meta.get_text())
        
        # Пытаемся извлечь из инструкций (ищем упоминания времени)
        instructions_text = self.extract_instructions()
        if instructions_text:
            # Ищем паттерны типа "30 minutos", "40 minutes"
            time_match = re.search(r'(\d+)\s*(?:minutos?|minutes?)', instructions_text, re.IGNORECASE)
            if time_match:
                return f"{time_match.group(1)} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в мета-данных рецепта
        prep_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-prep-time')
        if prep_time_meta:
            return self.clean_text(prep_time_meta.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в мета-данных рецепта
        total_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-total-time')
        if total_time_meta:
            return self.clean_text(total_time_meta.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секции с заметками после основного контента рецепта
        # Обычно это блоки с strong заголовками и списками
        content_div = self.soup.find('div', class_='nv-content-wrap')
        
        if content_div:
            # Ищем все параграфы со strong внутри и следующие за ними ul списки
            for strong in content_div.find_all('strong'):
                parent = strong.parent
                if parent and parent.name == 'p':
                    # Проверяем, что это похоже на заголовок совета
                    strong_text = self.clean_text(strong.get_text())
                    if strong_text and ':' in strong_text:
                        # Ищем следующий ul элемент
                        next_sibling = parent.find_next_sibling()
                        if next_sibling and next_sibling.name == 'ul':
                            # Извлекаем текст из li
                            for li in next_sibling.find_all('li'):
                                note_text = self.clean_text(li.get_text())
                                if note_text:
                                    notes.append(note_text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в wprm-fallback-recipe-meta-keyword
        keyword_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-keyword')
        if keyword_meta:
            text = self.clean_text(keyword_meta.get_text())
            if text:
                # Теги уже разделены запятыми
                return text
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
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
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item and item['url'] not in urls:
                                urls.append(item['url'])
                            elif 'contentUrl' in item and item['contentUrl'] not in urls:
                                urls.append(item['contentUrl'])
                        
                        # Article/WebPage с image
                        if item.get('@type') in ['Article', 'WebPage'] and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict):
                                img_url = img.get('@id') or img.get('url') or img.get('contentUrl')
                                if img_url and img_url not in urls:
                                    urls.append(img_url)
                            elif isinstance(img, str) and img not in urls:
                                urls.append(img)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ограничиваем до 3 изображений и возвращаем как строку через запятую
        if urls:
            unique_urls = []
            for url in urls:
                if url and url not in unique_urls:
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
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
    # Обрабатываем папку preprocessed/cozinhatradicional_com
    recipes_dir = os.path.join("preprocessed", "cozinhatradicional_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CozinhaTradicionalExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cozinhatradicional_com.py")


if __name__ == "__main__":
    main()
