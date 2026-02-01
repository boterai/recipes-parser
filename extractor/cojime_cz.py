"""
Экстрактор данных рецептов для сайта cojime.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CojimeCzExtractor(BaseRecipeExtractor):
    """Экстрактор для cojime.cz"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке статьи
        entry_title = self.soup.find('h1', class_='entry-title')
        if entry_title:
            title = self.clean_text(entry_title.get_text())
            # Убираем суффиксы типа "» CoJíme.cz" и длинные подзаголовки
            title = re.sub(r'\s*[»:]\s*CoJ[íi]me\.cz.*$', '', title, flags=re.IGNORECASE)
            # Убираем двоеточие и всё после него для краткости
            title = re.sub(r'\s*:\s*.+$', '', title)
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[»:]\s*CoJ[íi]me\.cz.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*:\s*.+$', '', title)
            return self.clean_text(title)
        
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем блок с ингредиентами в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовок "Ingredience" и следующий за ним список
        h2_tags = entry_content.find_all(['h2', 'h3', 'h4'])
        
        for h_tag in h2_tags:
            h_text = h_tag.get_text(strip=True).lower()
            
            # Проверяем, содержит ли заголовок слово "ingredience"
            if 'ingredience' in h_text or 'suroviny' in h_text:
                # Ищем следующий элемент списка
                next_elem = h_tag.find_next_sibling()
                
                while next_elem:
                    if next_elem.name == 'ul':
                        # Извлекаем элементы списка
                        items = next_elem.find_all('li', recursive=False)
                        for item in items:
                            ingredient_text = item.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text and len(ingredient_text) > 2:
                                # Создаем структурированный ингредиент
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        
                        if ingredients:
                            break
                    
                    # Также проверяем параграфы на случай, если список не оформлен через ul/li
                    elif next_elem.name == 'p':
                        text = next_elem.get_text(strip=True)
                        # Если это не пустой параграф и не начало нового раздела
                        if text and not any(keyword in text.lower() for keyword in ['recept', 'postup', 'příprava']):
                            next_elem = next_elem.find_next_sibling()
                            continue
                    
                    # Если встретили новый заголовок, прекращаем поиск
                    if next_elem.name in ['h2', 'h3', 'h4']:
                        break
                    
                    next_elem = next_elem.find_next_sibling()
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Kondenzované kokosové mléko (bez cukru)"
            
        Returns:
            dict: {"name": "...", "amount": None, "unit": None}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем скобки с содержимым (комментарии)
        name = re.sub(r'\([^)]*\)', '', text)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Для cojime.cz ингредиенты обычно без количества в списке
        # Поэтому возвращаем только название
        return {
            "name": name,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем блок с инструкциями в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовок с "recept", "postup", "příprava"
        h2_tags = entry_content.find_all(['h2', 'h3', 'h4'])
        
        for h_tag in h2_tags:
            h_text = h_tag.get_text(strip=True).lower()
            
            # Проверяем, содержит ли заголовок ключевые слова
            if any(keyword in h_text for keyword in ['recept', 'postup', 'příprava', 'návod']):
                # Ищем следующие элементы (параграфы, списки)
                next_elem = h_tag.find_next_sibling()
                
                while next_elem:
                    if next_elem.name == 'ol':
                        # Нумерованный список шагов
                        items = next_elem.find_all('li', recursive=False)
                        for item in items:
                            step_text = item.get_text(strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                instructions.append(step_text)
                        
                        if instructions:
                            break
                    
                    elif next_elem.name == 'ul':
                        # Ненумерованный список
                        items = next_elem.find_all('li', recursive=False)
                        for item in items:
                            step_text = item.get_text(strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                instructions.append(step_text)
                        
                        if instructions:
                            break
                    
                    elif next_elem.name == 'p':
                        # Параграф с инструкцией
                        text = next_elem.get_text(strip=True)
                        text = self.clean_text(text)
                        
                        # Пропускаем пустые и слишком короткие параграфы
                        if text and len(text) > 10:
                            instructions.append(text)
                    
                    # Если встретили новый заголовок, прекращаем
                    if next_elem.name in ['h2', 'h3', 'h4']:
                        break
                    
                    next_elem = next_elem.find_next_sibling()
                
                if instructions:
                    break
        
        # Если инструкции найдены, объединяем их
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в мета-тегах article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в breadcrumbs или тегах категорий
        category_tags = self.soup.find_all('a', rel='tag')
        if category_tags:
            categories = [self.clean_text(tag.get_text()) for tag in category_tags]
            if categories:
                return ', '.join(categories[:2])  # Берем первые 2 категории
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # cojime.cz обычно не разделяет prep/cook time в структурированном виде
        # Ищем упоминания времени в тексте
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секции с советами, заметками
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовки с "tipy", "poznámky", "rady"
        h2_tags = entry_content.find_all(['h2', 'h3', 'h4'])
        
        for h_tag in h2_tags:
            h_text = h_tag.get_text(strip=True).lower()
            
            if any(keyword in h_text for keyword in ['tipy', 'poznámk', 'rady', 'doporučen']):
                # Собираем текст из следующих параграфов
                notes = []
                next_elem = h_tag.find_next_sibling()
                
                while next_elem:
                    if next_elem.name == 'p':
                        text = next_elem.get_text(strip=True)
                        text = self.clean_text(text)
                        if text and len(text) > 10:
                            notes.append(text)
                    
                    elif next_elem.name == 'ul':
                        items = next_elem.find_all('li', recursive=False)
                        for item in items:
                            text = item.get_text(strip=True)
                            text = self.clean_text(text)
                            if text:
                                notes.append(text)
                    
                    # Если встретили новый заголовок, прекращаем
                    if next_elem.name in ['h2', 'h3', 'h4']:
                        break
                    
                    next_elem = next_elem.find_next_sibling()
                
                if notes:
                    return ' '.join(notes[:3])  # Берем первые 3 заметки
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags_str = meta_keywords['content']
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        # Если не нашли в keywords, ищем в ссылках с rel="tag"
        if not tags:
            tag_links = self.soup.find_all('a', rel='tag')
            if tag_links:
                tags = [self.clean_text(tag.get_text()) for tag in tag_links]
        
        # Если всё еще нет тегов, используем категории из JSON-LD
        if not tags:
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    
                    # Ищем в @graph
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'articleSection' in item:
                                section = item['articleSection']
                                if isinstance(section, str):
                                    tags = [s.strip() for s in section.split(',')]
                                elif isinstance(section, list):
                                    tags = section
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        if tags:
            # Фильтруем и нормализуем
            filtered_tags = []
            for tag in tags:
                tag = tag.lower().strip()
                if len(tag) > 2 and tag not in filtered_tags:
                    filtered_tags.append(tag)
            
            return ', '.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем featured image в статье
        featured_img = self.soup.find('img', class_='wp-post-image')
        if featured_img and featured_img.get('src'):
            url = featured_img['src']
            if url not in urls:
                urls.append(url)
        
        # 4. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            url = item['url']
                            if url not in urls:
                                urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ограничиваем до 3 изображений
        if urls:
            return ','.join(urls[:3])
        
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
    """Обработка HTML файлов из директории preprocessed/cojime_cz"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "cojime_cz")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CojimeCzExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/cojime_cz.py")


if __name__ == "__main__":
    main()
