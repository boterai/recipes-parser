"""
Экстрактор данных рецептов для сайта kuvarancije.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KuvarancipjeExtractor(BaseRecipeExtractor):
    """Экстрактор для kuvarancije.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph structure
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            return item
                
                # Проверяем прямой Article
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def _get_breadcrumb_data(self) -> Optional[dict]:
        """Извлечение данных breadcrumb из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Из JSON-LD Article
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем headline
            if 'headline' in json_ld:
                return self.clean_text(json_ld['headline'])
            # Пробуем name
            if 'name' in json_ld:
                return self.clean_text(json_ld['name'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем первую часть до запятой
            if ',' in desc:
                return self.clean_text(desc.split(',')[0])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем первое предложение (до первой точки)
            if '.' in desc:
                first_sentence = desc.split('.')[0] + '.'
                return self.clean_text(first_sentence)
            return self.clean_text(desc)
        
        # Из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            if '.' in desc:
                first_sentence = desc.split('.')[0] + '.'
                return self.clean_text(first_sentence)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 šolje integralnog pšeničnog brašna"
            
        Returns:
            dict: {"name": "integralnog pšeničnog brašna", "amount": 2, "units": "šolje"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Убираем запятые в конце
        text = text.rstrip(',')
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Сербские единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(šolje|šoljica|kašike|kašika|kašikica|kašičica|kasike|g|gr|kg|ml|l|dl|kom|komada?|komad|piece|pieces|tablespoon|tablespoons|kockica|kockice)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Возвращаем как число (int или float)
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Возвращаем как число (int или float)
                    amount = int(val) if val == int(val) else val
                except (ValueError, TypeError):
                    amount = amount_str
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем заголовок "Sastojci:" (может быть в p или h4)
        for elem in self.soup.find_all(['p', 'h4', 'h3']):
            elem_text = elem.get_text(strip=True)
            if elem_text == 'Sastojci:' or elem_text.lower() == 'sastojci:':
                # Нашли заголовок "Sastojci:", теперь ищем следующий ul
                ul = elem.find_next('ul')
                if ul:
                    lis = ul.find_all('li')
                    for li in lis:
                        ingredient_text = li.get_text(strip=True)
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Priprema:" (может быть в p или h4)
        found_priprema = False
        for elem in self.soup.find_all(['p', 'h4', 'h3', 'img']):
            if elem.name in ['p', 'h4', 'h3']:
                text = elem.get_text(strip=True)
                
                if text == 'Priprema:' or text.lower() == 'priprema:':
                    found_priprema = True
                    continue
                
                if found_priprema:
                    # Проверяем, не начинается ли новая секция или заметки
                    if (text.startswith('Napomena') or 
                        text.startswith('Jednostavnije mere') or
                        text.startswith('Osim') or
                        text.startswith('Sve u svemu')):
                        break
                    
                    # Пропускаем пустые параграфы и параграфы со скриптами
                    if text and len(text) > 10 and 'adsbygoogle' not in text:
                        steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из breadcrumbs"""
        breadcrumb = self._get_breadcrumb_data()
        
        if breadcrumb and 'itemListElement' in breadcrumb:
            items = breadcrumb['itemListElement']
            # Берем предпоследний элемент (последний - это сам рецепт)
            if len(items) >= 3:
                category_item = items[-2]
                category = category_item.get('name', '')
                # Маппинг полных названий на короткие
                category_mapping = {
                    'Testenina i testo': 'Testo',
                    'testenina i testo': 'Testo'
                }
                return self.clean_text(category_mapping.get(category, category))
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминание времени в минутах
        for p in self.soup.find_all('p'):
            text = p.get_text()
            # Ищем паттерны типа "30 minuta", "oko 30 minuta"
            time_match = re.search(r'(?:oko\s+)?(\d+)\s*minuta', text, re.IGNORECASE)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На kuvarancije.com обычно не разделяют prep и cook time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На kuvarancije.com обычно не указывают total time отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем параграф с "Napomena:" и собираем следующие параграфы (если есть)
        found_napomena = False
        for elem in self.soup.find_all(['p', 'h4', 'h3']):
            if elem.name in ['p', 'h4', 'h3']:
                text = elem.get_text(strip=True)
                
                if text == 'Napomena:' or text.lower() == 'napomena:':
                    found_napomena = True
                    continue
                
                if found_napomena:
                    # Собираем только непустые параграфы, но останавливаемся перед "Priprema:"
                    if text.endswith(':') and len(text) < 20:  # Это заголовок новой секции
                        break
                    if text and len(text) > 10 and 'adsbygoogle' not in text:
                        notes.append(text)
        
        # Если нашли заметки после "Napomena:", возвращаем их
        if notes:
            return ' '.join(notes)
        
        # Иначе ищем параграфы с характерными фразами для заметок/советов
        # Эти обычно идут ПОСЛЕ инструкций
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            # Ищем параграфы, которые начинаются с характерных фраз
            if text.startswith('Osim'):
                # Берем первое предложение или два
                sentences = text.split('.')
                if len(sentences) >= 2:
                    # Возвращаем первые два предложения
                    return '. '.join(sentences[:2]).strip() + '.'
                return text
            elif text.startswith('Jednostavnije mere'):
                # Берем первое предложение
                sentences = text.split('.')
                if sentences:
                    first_sentence = sentences[0] + '.'
                    # Если есть второе короткое предложение, добавляем его
                    if len(sentences) > 1 and len(sentences[1]) < 100:
                        return first_sentence + ' ' + sentences[1].strip() + '.'
                    return first_sentence
            elif text.startswith('Umesto'):
                return text.split('.')[0] + '.' if '.' in text else text
            elif text.startswith('Ovo su orijentacione mere'):
                # Берем только первое предложение
                return text.split('.')[0] + '.' if '.' in text else text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ссылок на странице"""
        tags = []
        
        # Ищем все ссылки на странице
        all_links = self.soup.find_all('a')
        
        # Сначала собираем теги из /component/tags/tag/
        for link in all_links:
            href = link.get('href', '')
            link_text = link.get_text(strip=True).lower()
            
            # Ищем только ссылки на теги
            if '/component/tags/tag/' in href:
                cleaned_tag = self.clean_text(link_text)
                if cleaned_tag and len(cleaned_tag) > 1:
                    if cleaned_tag.lower() not in [t.lower() for t in tags]:
                        tags.append(cleaned_tag.lower())
        
        # Добавляем некоторые специальные теги из категорий
        for link in all_links:
            href = link.get('href', '')
            link_text = link.get_text(strip=True).lower()
            
            # Обрабатываем "brzo i lako" -> "brzo", "jednostavno"
            if link_text == 'brzo i lako' or link_text == 'brzo i jednostavno':
                if 'brzo' not in tags:
                    tags.insert(0, 'brzo')
                if 'jednostavno' not in tags:
                    tags.insert(1, 'jednostavno')
            
            # Добавляем "bez mesa" из категории "jela bez mesa"
            if link_text == 'jela bez mesa' or href == '/recepti/jela-bez-mesa':
                if 'bez mesa' not in tags:
                    tags.append('bez mesa')
            
            # Добавляем "posno"
            if link_text == 'posno' or href == '/recepti/posno':
                if 'posno' not in tags:
                    tags.append('posno')
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD Article
        json_ld = self._get_json_ld_data()
        if json_ld:
            # Проверяем image field
            if 'image' in json_ld:
                img = json_ld['image']
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, list):
                    urls.extend([i for i in img if isinstance(i, str)])
            
            # Проверяем thumbnailUrl
            if 'thumbnailUrl' in json_ld:
                urls.append(json_ld['thumbnailUrl'])
        
        # 2. Из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Из img тегов в тексте рецепта (между "Priprema:" и концом)
        found_priprema = False
        for elem in self.soup.find_all(['p', 'img']):
            if elem.name == 'p' and 'Priprema' in elem.get_text():
                found_priprema = True
                continue
            
            if found_priprema and elem.name == 'img':
                src = elem.get('src', '')
                if src and 'images/stories/recepti' in src:
                    # Конвертируем относительный URL в абсолютный
                    if not src.startswith('http'):
                        src = 'https://www.kuvarancije.com/' + src.lstrip('/')
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "kuvarancije_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KuvarancipjeExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kuvarancije_com.py")


if __name__ == "__main__":
    main()
