"""
Экстрактор данных рецептов для сайта turkischerezepte.de
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TurkischeRezepteExtractor(BaseRecipeExtractor):
    """Экстрактор для turkischerezepte.de"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Попробуем из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем типичные суффиксы
            title = re.sub(r'\s*[–-]\s*.*$', '', title)  # Убираем всё после тире
            # Убираем слово "Rezept" в конце или начале
            title = re.sub(r'\s*Rezept\s*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Rezept\s*', '', title, flags=re.IGNORECASE)
            return title if title else None
        
        # Из мета-тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Убираем типичные суффиксы
            title = re.sub(r'\s*Rezept\s*[–-].*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*Rezept\s*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Rezept\s*', '', title, flags=re.IGNORECASE)
            return title if title else None
        
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
        
        # Или первый параграф после заголовка
        h1 = self.soup.find('h1')
        if h1:
            next_p = h1.find_next('p')
            if next_p:
                text = self.clean_text(next_p.get_text())
                return text if text else None
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента
        
        Args:
            text: Строка вида "1 KG Mehl" или "400 ml Wasser"
            
        Returns:
            dict: {"name": "Mehl", "amount": "1", "unit": "KG"} или None
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Пропускаем пустые строки и заголовки секций
        if not text or text.endswith(':'):
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 KG Mehl", "400 ml Wasser", "1/2 TL Salz", "Etwas Petersilie"
        pattern = r'^([\d\s/.,]+)?\s*(KG|kg|g|G|ml|ML|l|L|TL|EL|tl|el|Stück|stück|pieces?|piece)?[\s]*(.*)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                try:
                    parts = amount_str.split('/')
                    amount = str(float(parts[0]) / float(parts[1]))
                except:
                    amount = amount_str
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip() if name else text
        # Удаляем скобки с содержимым типа "(или Böreklik Käse, im türkischen Markt erhältlich)"
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "Etwas ", "Nach Bedarf"
        name = re.sub(r'^(Etwas|Nach Bedarf|Optional|nach Geschmack)\s+', '', name, flags=re.IGNORECASE)
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все ul элементы, которые содержат ингредиенты
        # Они обычно идут после заголовка "Zutaten"
        zutaten_header = None
        for elem in self.soup.find_all(['h2', 'h3', 'h4']):
            if 'zutaten' in elem.get_text().lower():
                zutaten_header = elem
                break
        
        if zutaten_header:
            # Ищем все ul после заголовка до следующего заголовка H2/H3
            current = zutaten_header.find_next_sibling()
            while current:
                # Останавливаемся на следующем важном заголовке
                if current.name in ['h2', 'h3']:
                    # Если это заголовок о приготовлении/инструкциях, останавливаемся
                    if any(word in current.get_text().lower() for word in ['zubereitung', 'anleitung', 'schritte']):
                        break
                
                # Обрабатываем списки
                if current.name == 'ul':
                    for li in current.find_all('li', recursive=False):
                        text = li.get_text(strip=True)
                        parsed = self.parse_ingredient_line(text)
                        if parsed and parsed['name']:
                            ingredients.append(parsed)
                
                # Также проверяем p с strong (для секций типа "FÜR DEN TEIG")
                # Но не добавляем их как ингредиенты
                
                current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Zubereitung"
        zubereitung_header = None
        for elem in self.soup.find_all(['h2', 'h3', 'h4']):
            if 'zubereitung' in elem.get_text().lower():
                zubereitung_header = elem
                break
        
        if zubereitung_header:
            # Ищем ol, ul или p после заголовка
            current = zubereitung_header.find_next_sibling()
            while current:
                # Останавливаемся на следующем важном заголовке
                if current.name in ['h2', 'h3', 'h4']:
                    break
                
                # Обрабатываем списки
                if current.name in ['ol', 'ul']:
                    for li in current.find_all('li', recursive=False):
                        text = li.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text and len(text) > 10:  # Игнорируем очень короткие строки
                            steps.append(text)
                
                # Обрабатываем параграфы (для рецептов без списков)
                elif current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    # Игнорируем параграфы с метаинформацией (время, количество)
                    if text and len(text) > 15 and not re.match(r'^(Zubereitungszeit|Für \d+)', text):
                        steps.append(text)
                
                current = current.find_next_sibling()
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD articleSection
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            if item.get('@type') == 'Article' and 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list) and sections:
                                    return self.clean_text(sections[0])
                                elif isinstance(sections, str):
                                    return self.clean_text(sections)
                                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из хлебных крошек
        breadcrumb = self.soup.find('nav', id='breadcrumb')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:  # Берем предпоследнюю категорию
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_sections = []
        
        # Ищем секции с примечаниями
        for elem in self.soup.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'b']):
            text = elem.get_text().lower()
            if any(word in text for word in ['kernpunkt', 'tipp', 'hinweis', 'note']):
                # Берем следующий параграф
                next_p = elem.find_next('p')
                if next_p:
                    note_text = self.clean_text(next_p.get_text())
                    if note_text:
                        notes_sections.append(note_text)
        
        return ' '.join(notes_sections) if notes_sections else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    return ', '.join(keywords)
                                elif isinstance(keywords, str):
                                    return keywords
                                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    urls.append(item['url'])
                                elif 'contentUrl' in item:
                                    urls.append(item['contentUrl'])
                            # Article с image
                            elif item.get('@type') == 'Article' and 'image' in item:
                                img = item['image']
                                if isinstance(img, dict) and '@id' in img:
                                    # Это ссылка на ImageObject, уже обработаем отдельно
                                    pass
                                elif isinstance(img, str):
                                    urls.append(img)
                                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Главное изображение из featured area
        featured_img = self.soup.find('figure', class_='single-featured-image')
        if featured_img:
            img = featured_img.find('img')
            if img and img.get('src'):
                src = img['src']
                # Пропускаем data: URLs
                if not src.startswith('data:'):
                    urls.append(src)
            # Также проверяем data-src
            if img and img.get('data-src'):
                urls.append(img['data-src'])
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen and not url.startswith('data:'):
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": None,  # Обычно не указывается на turkischerezepte.de
            "cook_time": None,
            "total_time": None,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """
    Точка входа для обработки HTML-файлов из preprocessed/turkischerezepte_de
    """
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "turkischerezepte_de"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(TurkischeRezepteExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python turkischerezepte_de.py")


if __name__ == "__main__":
    main()
