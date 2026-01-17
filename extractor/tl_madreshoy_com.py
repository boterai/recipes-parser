"""
Экстрактор данных рецептов для сайта tl.madreshoy.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TlMadreshoyComExtractor(BaseRecipeExtractor):
    """Экстрактор для tl.madreshoy.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Ищем NewsArticle (на этом сайте рецепты в NewsArticle, не Recipe)
                if isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if item_type == 'NewsArticle':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'headline' in json_ld:
            return self.clean_text(json_ld['headline'])
        
        # Пробуем из мета-тегов
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Пробуем из H1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Пробуем из мета-тегов
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из текста статьи
        Возвращает JSON-строку со списком словарей
        """
        ingredients = []
        
        # Сначала пробуем из JSON-LD articleBody
        json_ld = self._get_json_ld_data()
        if json_ld and 'articleBody' in json_ld:
            article_body = json_ld['articleBody']
            # Ищем секцию ингредиентов в тексте
            lines = article_body.split('\n')
            in_ingredients_section = False
            
            for line in lines:
                line = line.strip()
                # Проверяем начало секции ингредиентов
                if any(keyword in line.lower() for keyword in ['sangkap', 'ingredients', 'kailangan']):
                    in_ingredients_section = True
                    continue
                
                # Проверяем конец секции (начало инструкций)
                if in_ingredients_section and any(keyword in line.lower() for keyword in ['paano', 'hakbang', 'step', 'instruction']):
                    break
                
                # Извлекаем ингредиенты
                if in_ingredients_section and line:
                    parsed = self._parse_ingredient(line)
                    if parsed and parsed['name']:
                        ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not ingredients:
            content_area = self.soup.find(class_=re.compile(r'post-content|article-content|entry-content', re.I))
            if content_area:
                # Ищем списки
                lists = content_area.find_all('ul')
                for ul in lists:
                    items = ul.find_all('li')
                    for item in items:
                        text = self.clean_text(item.get_text())
                        if text and len(text) > 2:
                            parsed = self._parse_ingredient(text)
                            if parsed and parsed['name']:
                                ingredients.append(parsed)
                    
                    if len(ingredients) >= 3:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _parse_ingredient(self, text: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента
        
        Args:
            text: Строка с ингредиентом
            
        Returns:
            dict с полями name, amount, unit или None
        """
        if not text or len(text) < 2:
            return None
        
        text = self.clean_text(text).lower()
        
        # Базовая структура
        ingredient = {
            "name": None,
            "amount": None,
            "unit": None
        }
        
        # Паттерн для извлечения количества и единиц измерения
        # Примеры: "200 gr", "1 clove", "2 tablespoons", "50 g"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)?\s+(.+)$'
        match = re.match(pattern, text)
        
        if match:
            amount_str = match.group(1).replace(',', '.')
            unit = match.group(2) if match.group(2) else None
            name = match.group(3).strip()
            
            ingredient['amount'] = amount_str
            ingredient['unit'] = unit
            ingredient['name'] = name
        else:
            # Если не нашли количество, просто записываем название
            ingredient['name'] = text
        
        return ingredient
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления в виде строки"""
        steps = []
        
        # Сначала пробуем из JSON-LD articleBody
        json_ld = self._get_json_ld_data()
        if json_ld and 'articleBody' in json_ld:
            article_body = json_ld['articleBody']
            # Ищем секцию инструкций в тексте
            lines = article_body.split('\n')
            in_instructions_section = False
            
            for line in lines:
                line = line.strip()
                # Проверяем начало секции инструкций
                if any(keyword in line.lower() for keyword in ['paano', 'hakbang', 'step', 'instruction', 'preparation']):
                    in_instructions_section = True
                    continue
                
                # Извлекаем шаги
                if in_instructions_section and line:
                    # Проверяем, начинается ли с цифры или маркера шага
                    if re.match(r'^\d+\.?\s', line) or re.match(r'^-\s', line):
                        steps.append(line)
                    # Или просто текст после секции инструкций
                    elif len(steps) > 0:  # Уже начали собирать шаги
                        # Останавливаемся на новой секции
                        if any(keyword in line.lower() for keyword in ['sangkap', 'note', 'tip']):
                            break
                        steps.append(line)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not steps:
            content_area = self.soup.find(class_=re.compile(r'post-content|article-content|entry-content', re.I))
            
            if content_area:
                # Ищем нумерованные списки (ol)
                ordered_lists = content_area.find_all('ol')
                for ol in ordered_lists:
                    items = ol.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            if not re.match(r'^\d+\.', step_text):
                                steps.append(f"{idx}. {step_text}")
                            else:
                                steps.append(step_text)
                    
                    if steps:
                        break
                
                # Если не нашли ol, ищем абзацы с шагами
                if not steps:
                    paragraphs = content_area.find_all('p')
                    for p in paragraphs:
                        text = self.clean_text(p.get_text())
                        if text and re.match(r'^\d+\.', text):
                            steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'articleSection' in json_ld:
            return self.clean_text(json_ld['articleSection'])
        
        # Пробуем из мета-тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Пробуем из breadcrumbs
        breadcrumbs = self.soup.find('nav', id='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем последнюю категорию перед рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте упоминания prep time
        content = self.soup.get_text()
        
        # Паттерны для поиска времени подготовки
        patterns = [
            r'prep(?:aration)?\s*time[:\s]*(\d+\s*(?:minutes?|mins?|hours?|hrs?))',
            r'paghahanda[:\s]*(\d+\s*(?:minutes?|mins?|minuto|oras))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминания cook time
        content = self.soup.get_text()
        
        patterns = [
            r'cook(?:ing)?\s*time[:\s]*(\d+\s*(?:minutes?|mins?|hours?|hrs?))',
            r'pagluluto[:\s]*(\d+\s*(?:minutes?|mins?|minuto|oras))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте упоминания total time
        content = self.soup.get_text()
        
        patterns = [
            r'total\s*time[:\s]*(\d+\s*(?:minutes?|mins?|hours?|hrs?))',
            r'kabuuang\s*oras[:\s]*(\d+\s*(?:minutes?|mins?|minuto|oras))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с заметками/советами
        content_area = self.soup.find(class_=re.compile(r'post-content|article-content|entry-content', re.I))
        
        if content_area:
            # Ищем заголовки с "notes", "tips", "paalala"
            headings = content_area.find_all(['h2', 'h3', 'h4', 'strong'])
            for heading in headings:
                heading_text = self.clean_text(heading.get_text().lower())
                if any(keyword in heading_text for keyword in ['note', 'tip', 'paalala', 'advice', 'suggestion']):
                    # Берем следующий элемент
                    next_elem = heading.find_next_sibling()
                    if next_elem:
                        notes_text = self.clean_text(next_elem.get_text())
                        if notes_text:
                            return notes_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем из мета-тегов
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content'].split(',')
            tags.extend([self.clean_text(k) for k in keywords if k.strip()])
        
        # Пробуем из ссылок на теги
        tag_links = self.soup.find_all('a', rel='tag')
        for link in tag_links:
            tag_text = self.clean_text(link.get_text())
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Пробуем из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            # Фильтруем placeholder SVG
            if not img_url.startswith('data:image/svg'):
                urls.append(img_url)
        
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            img_url = twitter_image['content']
            if img_url not in urls and not img_url.startswith('data:image/svg'):
                urls.append(img_url)
        
        # 2. Пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, dict) and 'url' in img:
                img_url = img['url']
                if img_url not in urls and not img_url.startswith('data:image/svg'):
                    urls.append(img_url)
            elif isinstance(img, str) and img not in urls and not img.startswith('data:image/svg'):
                urls.append(img)
        
        # 3. Ищем изображения в основном контенте
        content_area = self.soup.find(class_=re.compile(r'post-content|article-content|entry-content', re.I))
        if content_area and len(urls) < 3:
            images = content_area.find_all('img', src=True)
            for img in images:
                src = img['src']
                # Фильтруем маленькие изображения, иконки и placeholder SVG
                if src and not any(x in src.lower() for x in ['icon', 'logo', 'avatar', 'emoji']) and not src.startswith('data:image/svg'):
                    # Проверяем размер если указан
                    width = img.get('width')
                    if width and int(width) < 100:
                        continue
                    
                    if src not in urls:
                        urls.append(src)
                    
                    if len(urls) >= 3:
                        break
        
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
    """
    Обработка всех HTML файлов в директории preprocessed/tl_madreshoy_com
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "tl_madreshoy_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(TlMadreshoyComExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python tl_madreshoy_com.py")


if __name__ == "__main__":
    main()
