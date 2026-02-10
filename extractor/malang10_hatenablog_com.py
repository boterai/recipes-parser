"""
Экстрактор данных рецептов для сайта malang10.hatenablog.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Malang10HatenablogComExtractor(BaseRecipeExtractor):
    """Экстрактор для malang10.hatenablog.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        entry_title = self.soup.find('a', class_='entry-title-link')
        if entry_title:
            title = entry_title.get_text(strip=True)
            # Убираем суффиксы типа " - the cooking kitchen"
            title = re.sub(r'\s*[-–]\s*.*$', '', title)
            # Извлекаем только часть до двоеточия или "の"
            # Примеры: 
            # "スロークッカーで作るビーフシチュー：..." -> "ビーフシチュー"
            # "ワンパン鶏肉と野菜の旨味：..." -> "ワンパン鶏肉と野菜"
            # "エキゾチックなモロッコのタジン：..." -> "タジン"
            
            # Сначала пробуем паттерн "で作る[название]"
            match = re.search(r'で作る(.+?)(?:[：:]|$)', title)
            if match:
                dish = match.group(1).strip()
                return self.clean_text(dish)
            
            # Извлекаем часть до двоеточия
            parts = re.split(r'[：:]', title)
            if parts:
                dish_part = parts[0].strip()
                
                # Убираем описательные префиксы типа "エキゾチックな", "シンプルで"
                # и оставляем только главное название
                # Примеры: "エキゾチックなモロッコのタジン" -> "タジン"
                #          "ワンパン鶏肉と野菜の旨味" -> "ワンパン鶏肉と野菜"
                
                # Если есть "の" в конце с описанием, убираем это описание
                match_no = re.match(r'(.+?)の(?:旨味|風味|魅力|美味しさ|作り方|レシピ)$', dish_part)
                if match_no:
                    dish = match_no.group(1).strip()
                    return self.clean_text(dish)
                
                # Убираем префиксные прилагательные перед "の"
                match_prefix = re.match(r'(?:エキゾチックな|伝統的な|本格的な|簡単な|美味しい)(.+)', dish_part)
                if match_prefix:
                    dish = match_prefix.group(1).strip()
                    # Еще раз проверяем на "の[страна]の[блюдо]"
                    match_country = re.match(r'.+の(.+)$', dish)
                    if match_country:
                        final_dish = match_country.group(1).strip()
                        return self.clean_text(final_dish)
                    return self.clean_text(dish)
                
                return self.clean_text(dish_part)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–]\s*.*$', '', title)
            
            match = re.search(r'で作る(.+?)(?:[：:]|$)', title)
            if match:
                dish = match.group(1).strip()
                return self.clean_text(dish)
            
            parts = re.split(r'[：:]', title)
            if parts:
                dish_part = parts[0].strip()
                match_no = re.match(r'(.+?)の(?:旨味|風味|魅力|美味しさ|作り方|レシピ)$', dish_part)
                if match_no:
                    return self.clean_text(match_no.group(1).strip())
                return self.clean_text(dish_part)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в основном контенте первый параграф с содержательным текстом
        entry = self.soup.find('div', class_='hatenablog-entry')
        if entry:
            # Ищем параграфы до первого заголовка h2
            for elem in entry.children:
                if hasattr(elem, 'name'):
                    if elem.name == 'h2':
                        break  # Дошли до первого заголовка, прекращаем поиск
                    elif elem.name == 'p':
                        text = elem.get_text(strip=True)
                        # Пропускаем рекламу и короткие тексты
                        if text and len(text) > 20 and '広告' not in text:
                            # Извлекаем только первое предложение
                            sentences = re.split(r'[。！？]', text)
                            if sentences and sentences[0]:
                                return self.clean_text(sentences[0] + '。')
        
        # Альтернативно - используем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        Примеры японского формата:
        - "牛肉 500g" -> {"name": "牛肉", "amount": 500, "units": "g"}
        - "玉ねぎ 1個" -> {"name": "玉ねぎ", "amount": 1, "units": "個"}
        - "塩・黒胡椒 適量" -> {"name": "塩・黒胡椒", "amount": None, "units": "適量"}
        - "牛肉（肩ロース）500g" -> {"name": "牛肉", "amount": 500, "units": "g"}
        - "鶏もも肉：500g" -> {"name": "鶏もも肉", "amount": 500, "units": "g"}
        """
        text = self.clean_text(text)
        if not text:
            return None
        
        # Сначала удаляем скобки с описаниями (например, "（みじん切り）")
        text_clean = re.sub(r'[（(][^）)]*[）)]', '', text).strip()
        
        # Убираем японское двоеточие "：" в начале или после названия
        text_clean = re.sub(r'[:：]\s*', ' ', text_clean).strip()
        
        # Паттерн для парсинга: название, количество, единица
        # Поддержка форматов: "牛肉 500g", "玉ねぎ 1個", "大さじ2", "適量"
        pattern = r'^(.+?)\s+(\d+(?:[.,]\d+)?|適量|少々|お好み)?(?:\s*[-~〜]\s*\d+(?:[.,]\d+)?)?\s*(g|kg|ml|l|個|本|片|枚|株|大さじ|小さじ|カップ|適量|少々|お好み|個分)?$'
        
        match = re.match(pattern, text_clean)
        
        if not match:
            # Если паттерн не совпал, пробуем простой вариант без пробелов
            # Формат: "牛肉500g"
            pattern2 = r'^(.+?)(\d+(?:[.,]\d+)?)(g|kg|ml|l|個|本|片|枚|株|カップ|個分)$'
            match2 = re.match(pattern2, text_clean)
            if match2:
                name, amount, units = match2.groups()
            else:
                # Возвращаем только название
                # Убираем trailing двоеточия и пробелы
                clean_name = text_clean.rstrip('：: ')
                return {
                    "name": clean_name if clean_name else text_clean,
                    "amount": None,
                    "units": None
                }
        else:
            name, amount, units = match.groups()
        
        # Очищаем имя от trailing двоеточий и пробелов
        name = self.clean_text(name).rstrip('：: ')
        
        # Обработка количества
        if amount and amount not in ['適量', '少々', 'お好み']:
            try:
                amount_val = float(amount.replace(',', '.'))
                if amount_val.is_integer():
                    amount = int(amount_val)
                else:
                    amount = amount_val
            except ValueError:
                pass
        elif amount in ['適量', '少々', 'お好み']:
            # Если это "適量", сохраняем как units
            if not units:
                units = amount
            amount = None
        else:
            amount = None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "材料" (ингредиенты)
        ingredients_header = self.soup.find('h2', id='材料')
        if not ingredients_header:
            # Альтернативный поиск
            ingredients_header = self.soup.find('h2', string=re.compile(r'材料'))
        
        if not ingredients_header:
            # Еще один вариант: "タジンの材料" или подобное
            ingredients_header = self.soup.find('h2', id=re.compile(r'材料'))
        
        if ingredients_header:
            # Вариант 1: Прямой <ul> после заголовка
            ul = ingredients_header.find_next_sibling('ul')
            if ul:
                items = ul.find_all('li', recursive=False)
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    parsed = self.parse_ingredient_text(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            # Вариант 2: Ингредиенты в subsections с <h3>
            if not ingredients:
                current = ingredients_header.find_next_sibling()
                while current and current.name != 'h2':
                    if current.name == 'h3':
                        # Подсекция с ингредиентами
                        next_elem = current.find_next_sibling()
                        if next_elem and next_elem.name == 'p':
                            # Текст ингредиентов в параграфе
                            text = next_elem.get_text(strip=True)
                            # Разбиваем по запятым или точкам с запятой
                            parts = re.split(r'[、,;]', text)
                            for part in parts:
                                parsed = self.parse_ingredient_text(part.strip())
                                if parsed and parsed['name']:
                                    ingredients.append(parsed)
                    elif current.name == 'ul':
                        # Список ингредиентов
                        items = current.find_all('li', recursive=False)
                        for item in items:
                            ingredient_text = item.get_text(separator=' ', strip=True)
                            parsed = self.parse_ingredient_text(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "作り方" (способ приготовления)
        instructions_header = self.soup.find('h2', id='作り方')
        if not instructions_header:
            # Альтернативный поиск
            instructions_header = self.soup.find('h2', string=re.compile(r'作り方'))
        
        if not instructions_header:
            # Ищем также "調理法" (метод приготовления)
            instructions_header = self.soup.find('h2', id=re.compile(r'調理法'))
        
        if instructions_header:
            # Вариант 1: Инструкции в виде <ol>
            ol = instructions_header.find_next_sibling('ol')
            if ol:
                items = ol.find_all('li', recursive=False)
                for idx, item in enumerate(items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Добавляем нумерацию, если её нет
                        if not re.match(r'^\d+\.', step_text):
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
            
            # Вариант 2: Инструкции в виде <h3> + <p>
            if not steps:
                current = instructions_header.find_next_sibling()
                step_num = 0
                
                while current and current.name != 'h2':
                    if current.name == 'h3':
                        # Это заголовок шага
                        step_title = current.get_text(strip=True)
                        step_num += 1
                        
                        # Ищем следующий <p> с описанием шага
                        next_p = current.find_next_sibling('p')
                        if next_p:
                            step_desc = next_p.get_text(separator=' ', strip=True)
                            step_desc = self.clean_text(step_desc)
                            
                            # Извлекаем номер и название из заголовка, если есть
                            # Примеры: "1. 下準備", "ステップ1: 準備"
                            step_match = re.match(r'(?:ステップ)?(\d+)[.:：]\s*(.+)', step_title)
                            if step_match:
                                step_name = step_match.group(2).strip()
                                step_text = f"{step_num}. {step_name}: {step_desc}"
                            else:
                                # Убираем номер из заголовка, если он там есть
                                step_title_clean = re.sub(r'^\d+[.:：]\s*', '', step_title)
                                step_text = f"{step_num}. {step_title_clean}: {step_desc}"
                            
                            steps.append(step_text)
                    
                    current = current.find_next_sibling()
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем категорию в article:tag meta
        meta_tag = self.soup.find('meta', property='article:tag')
        if meta_tag and meta_tag.get('content'):
            # Обычно это "cooking" или другая общая категория
            # Возвращаем стандартное значение "Main Course" для рецептов
            return "Main Course"
        
        # Ищем в ссылках категорий
        category_link = self.soup.find('a', class_=re.compile(r'entry-category-link'))
        if category_link:
            # Возвращаем стандартное значение
            return "Main Course"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В данном формате блога время обычно не выделено отдельно
        # Возвращаем None, если не найдено явных указаний
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Ищем в тексте инструкций упоминания времени
        instructions = self.extract_instructions()
        if instructions:
            # Паттерн для поиска времени в японском тексте
            # Примеры: "6〜8時間", "15〜20分", "30分"
            time_patterns = [
                r'(\d+\s*[-~〜]\s*\d+)\s*時間',  # X~Y часов
                r'(\d+)\s*時間',  # X часов
                r'(\d+\s*[-~〜]\s*\d+)\s*分',  # X~Y минут
                r'(\d+)\s*分',  # X минут
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, instructions)
                if match:
                    time_str = match.group(0)
                    # Переводим японские обозначения в английские
                    time_str = time_str.replace('時間', ' hours').replace('分', ' minutes')
                    time_str = time_str.replace('〜', '-').replace('~', '-')
                    return time_str.strip()
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пытаемся найти общее время в инструкциях
        cook_time = self.extract_cook_time()
        if cook_time:
            return cook_time
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после секции "作り方" (инструкции)
        # Обычно заметки идут в секциях типа "提供の仕方" или других h2 после инструкций
        entry = self.soup.find('div', class_='hatenablog-entry')
        if entry:
            # Ищем заголовок "作り方"
            instructions_h2 = entry.find('h2', id='作り方')
            if not instructions_h2:
                instructions_h2 = entry.find('h2', string=re.compile(r'作り方'))
            
            if instructions_h2:
                # Ищем следующие заголовки и параграфы после инструкций
                current = instructions_h2.find_next_sibling()
                skip_first_ol = False
                
                while current:
                    if current.name == 'ol' and not skip_first_ol:
                        # Пропускаем сам список инструкций
                        skip_first_ol = True
                    elif current.name == 'h2':
                        # Нашли следующий раздел, ищем параграфы в нем
                        next_p = current.find_next_sibling('p')
                        if next_p:
                            text = next_p.get_text(strip=True)
                            if text and len(text) > 10:
                                # Извлекаем только релевантную часть (обычно после "また、")
                                # Пример: "... また、冷凍保存も可能なので..."
                                match = re.search(r'(?:また、?|さらに、?)(.+)', text)
                                if match:
                                    return self.clean_text(match.group(1))
                                return self.clean_text(text)
                        break
                    elif current.name == 'p' and skip_first_ol:
                        # Параграф сразу после списка инструкций
                        text = current.get_text(strip=True)
                        if text and len(text) > 10:
                            return self.clean_text(text)
                    
                    current = current.find_next_sibling()
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = set()
        
        # 1. Ищем keyword links (основной источник тегов в Hatena Blog)
        keywords = self.soup.find_all('a', class_='keyword')
        for kw in keywords:
            tag = kw.get_text(strip=True)
            if tag:
                tags.add(tag)
        
        # 2. Ищем в секции entry-tags (если есть)
        entry_tags = self.soup.find('div', class_='entry-tags')
        if entry_tags:
            tag_links = entry_tags.find_all('a', class_='entry-tag')
            for tag_link in tag_links:
                tag = tag_link.get_text(strip=True)
                if tag:
                    tags.add(tag)
        
        # 3. Если нет тегов, ищем в meta
        if not tags:
            meta_tag = self.soup.find('meta', property='article:tag')
            if meta_tag and meta_tag.get('content'):
                tags.add(meta_tag['content'])
        
        # Сортируем и возвращаем как строку через запятую
        if tags:
            return ', '.join(sorted(tags))
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Получаем оригинальный URL из CDN URL
            # Пример: https://cdn.image.st-hatena.com/.../https%3A%2F%2Fcdn-ak.f.st-hatena.com%2F...
            cdn_match = re.search(r'https%3A%2F%2F[^/]+\.f\.st-hatena\.com[^"\']*', url)
            if cdn_match:
                original_url = cdn_match.group(0).replace('%2F', '/').replace('%3A', ':')
                urls.append(original_url)
            else:
                urls.append(url)
        
        # 2. Ищем изображения в контенте
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img', class_='hatena-fotolife')
            for img in images:
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
                    if len(urls) >= 3:  # Ограничиваем до 3 изображений
                        break
        
        # 3. Дополнительно ищем в JSON-LD
        if len(urls) < 3:
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and 'image' in data:
                        images = data['image']
                        if isinstance(images, list):
                            for img in images:
                                if img and img not in urls:
                                    urls.append(img)
                                    if len(urls) >= 3:
                                        break
                        elif isinstance(images, str) and images not in urls:
                            urls.append(images)
                except (json.JSONDecodeError, KeyError):
                    continue
        
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
    # По умолчанию обрабатываем папку preprocessed/malang10_hatenablog_com
    preprocessed_dir = os.path.join("preprocessed", "malang10_hatenablog_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(Malang10HatenablogComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python malang10_hatenablog_com.py")


if __name__ == "__main__":
    main()
