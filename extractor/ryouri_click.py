"""
Экстрактор данных рецептов для сайта ryouri.click
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RyouriClickExtractor(BaseRecipeExtractor):
    """Экстрактор для ryouri.click"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта h1
        h1 = self.soup.find('h1', class_='wp-block-post-title')
        if h1:
            text = h1.get_text(strip=True)
            # Убираем суффиксы "のレシピ", "のレシピ・作り方" и т.д.
            text = re.sub(r'のレシピ.*$', '', text)
            return self.clean_text(text)
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            headline = item['headline']
                            headline = re.sub(r'のレシピ.*$', '', headline)
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Последняя попытка - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'のレシピ.*$', '', title)
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
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') in ['WebPage', ['WebPage', 'FAQPage']] and 'description' in item:
                            return self.clean_text(item['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем секцию с заголовком "材料" (Ingredients)
        h3_tags = self.soup.find_all('h3')
        for h3 in h3_tags:
            if '材料' in h3.get_text():
                # Находим следующий <ul> после этого заголовка
                section = h3.find_parent('section')
                if not section:
                    section = h3.find_next_sibling()
                
                # Ищем <ul> в этой секции
                ul = None
                if section:
                    ul = section.find('ul')
                if not ul:
                    ul = h3.find_next('ul')
                
                if ul:
                    # Извлекаем каждый ингредиент из <li>
                    for li in ul.find_all('li', recursive=True):
                        # Получаем все span элементы
                        spans = li.find_all('span')
                        
                        # Случай 1: Есть структура со span-ами (более сложная)
                        if spans and len(spans) >= 2:
                            # Первый span содержит имя и иногда часть количества
                            name_text = spans[0].get_text(strip=True)
                            
                            # Разделяем имя и количество
                            name_match = re.match(r'^(.+?)\s+([\d\.]+)$', name_text)
                            if name_match:
                                name = name_match.group(1).strip()
                                amount_part1 = name_match.group(2)
                            else:
                                name = name_text.strip()
                                amount_part1 = None
                            
                            # Следующие span-ы могут содержать дополнительную часть количества и единицу
                            amount = amount_part1
                            unit = None
                            
                            # Обрабатываем остальные span-ы
                            for i, span in enumerate(spans[1:], 1):
                                span_text = span.get_text(strip=True)
                                # Пропускаем описания (обычно длинные тексты с запятыми или с символом "、")
                                if '、' in span_text or len(span_text) > 20:
                                    continue
                                
                                # Проверяем, является ли это единицей измерения
                                units_pattern = r'(カップ|小さじ|大さじ|グラム|個|オンス|ミリリットル|リットル|ポンド|キログラム|g|ml|kg|lb|oz|杯|枚|本|つ|片)'
                                if re.search(units_pattern, span_text):
                                    unit = span_text
                                # Если это дробь или число (например, "と1/2")
                                elif re.search(r'[\d/]', span_text):
                                    # Добавляем к количеству
                                    if amount:
                                        # Обрабатываем "と1/2" -> добавляем к amount
                                        fraction_match = re.search(r'と?([\d/\.]+)', span_text)
                                        if fraction_match:
                                            fraction_text = fraction_match.group(1)
                                            # Преобразуем дробь в десятичное число
                                            if '/' in fraction_text:
                                                parts = fraction_text.split('/')
                                                if len(parts) == 2:
                                                    try:
                                                        fraction_value = float(parts[0]) / float(parts[1])
                                                        amount = str(float(amount) + fraction_value)
                                                    except ValueError:
                                                        pass
                                            else:
                                                try:
                                                    amount = str(float(amount) + float(fraction_text))
                                                except ValueError:
                                                    pass
                                    else:
                                        amount = span_text.replace('と', '')
                            
                            # Очистка названия от лишних символов
                            name = re.sub(r'[,、，]+$', '', name).strip()
                            
                            if name:
                                ingredients.append({
                                    "name": name,
                                    "amount": amount,
                                    "unit": unit
                                })
                        
                        # Случай 2: Простой формат - текст прямо в <li> без множества span-ов
                        else:
                            li_text = li.get_text(strip=True)
                            if not li_text:
                                continue
                            
                            # Парсим текст вида "牛ひき肉 1ポンド" или "玉ねぎ 1個（みじん切り）"
                            # Удаляем примечания в скобках
                            clean_text = re.sub(r'（[^）]*）', '', li_text)
                            clean_text = re.sub(r'\([^)]*\)', '', clean_text)
                            
                            # Паттерн: "название количество+единица" или просто "название"
                            # Примеры: "牛ひき肉 1ポンド", "塩 小さじ1/2"
                            pattern = r'^(.+?)\s+([\d./]+)\s*(.*)$'
                            match = re.match(pattern, clean_text)
                            
                            if match:
                                name = match.group(1).strip()
                                amount = match.group(2).strip()
                                unit = match.group(3).strip() if match.group(3) else None
                            else:
                                # Нет количества - только название
                                name = clean_text.strip()
                                amount = None
                                unit = None
                            
                            if name:
                                ingredients.append({
                                    "name": name,
                                    "amount": amount,
                                    "unit": unit
                                })
                    
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем секцию с заголовком "説明書" (Instructions)
        h3_tags = self.soup.find_all('h3')
        for h3 in h3_tags:
            if '説明書' in h3.get_text():
                # Находим родительскую секцию или следующий элемент
                section = h3.find_parent('section')
                if not section:
                    section = h3.find_next_sibling()
                
                if section:
                    # Ищем все <ol> в секции (может быть несколько - для разных частей рецепта)
                    ol_tags = section.find_all('ol')
                    for ol in ol_tags:
                        for li in ol.find_all('li', recursive=False):
                            text = li.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                instructions.append(text)
                    
                    if instructions:
                        break
        
        # Объединяем все инструкции в одну строку
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках (BreadcrumbList) - берем первую категорию (самую общую)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            items = item['itemListElement']
                            # Берем первую категорию (самую общую) - обычно items[0]
                            if len(items) >= 1:
                                category_item = items[0]
                                if 'name' in category_item:
                                    return self.clean_text(category_item['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - ищем в JSON-LD (articleSection)
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Возвращаем первую (наиболее общую) категорию
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени по метке
        
        Args:
            time_label: Метка времени на японском ('準備', '調理', '合計', etc.)
        """
        # Ищем div с меткой времени - должен быть коротким и содержать только время
        divs = self.soup.find_all('div')
        for div in divs:
            text = div.get_text(strip=True)
            # Проверяем, содержит ли div нужную метку и текст короткий (< 50 символов)
            if time_label in text and len(text) < 50:
                # Проверяем, что это точное совпадение формата "準備：20分"
                if re.match(rf'^{time_label}[：:]\s*\d', text):
                    # Ищем <strong> внутри этого div
                    strong = div.find('strong')
                    if strong:
                        time_text = strong.get_text(strip=True)
                        return self.clean_text(time_text)
                    # Если нет strong, пробуем извлечь из текста
                    # Паттерн: "準備： 20分"
                    match = re.search(rf'{time_label}[：:]\s*(.+)', text)
                    if match:
                        return self.clean_text(match.group(1))
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('準備')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('調理')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('合計')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заметками/советами
        # Обычно это секция после инструкций или с ключевыми словами
        h2_tags = self.soup.find_all('h2')
        h3_tags = self.soup.find_all('h3')
        
        # Ключевые слова для поиска заметок
        notes_keywords = ['ノート', 'メモ', 'コツ', 'ポイント', 'ヒント']
        
        for header in h2_tags + h3_tags:
            header_text = header.get_text()
            for keyword in notes_keywords:
                if keyword in header_text:
                    # Находим следующий элемент с текстом
                    next_elem = header.find_next_sibling()
                    if next_elem:
                        text = next_elem.get_text(separator=' ', strip=True)
                        return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD (articleSection может содержать теги)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                tags.extend(sections)
                            elif isinstance(sections, str):
                                tags.append(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Также проверяем хлебные крошки
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            items = item['itemListElement']
                            # Добавляем все категории из breadcrumb (кроме последней - это сам рецепт)
                            for breadcrumb_item in items[:-1]:
                                if 'name' in breadcrumb_item:
                                    tag_name = breadcrumb_item['name']
                                    if tag_name not in tags:
                                        tags.append(tag_name)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Возвращаем теги через запятую
        if tags:
            # Очищаем и убираем дубликаты
            cleaned_tags = []
            seen = set()
            for tag in tags:
                tag = self.clean_text(tag)
                if tag and tag not in seen:
                    seen.add(tag)
                    cleaned_tags.append(tag)
            return ', '.join(cleaned_tags) if cleaned_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Из twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Обрабатываем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item and item['url'] not in urls:
                                urls.append(item['url'])
                            elif 'contentUrl' in item and item['contentUrl'] not in urls:
                                urls.append(item['contentUrl'])
                        # Article с image
                        elif item.get('@type') == 'Article' and 'image' in item:
                            images = item['image']
                            if isinstance(images, list):
                                for img in images:
                                    if isinstance(img, str) and img not in urls:
                                        urls.append(img)
                            elif isinstance(images, str) and images not in urls:
                                urls.append(images)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 4. Из основного изображения страницы (featured image)
        featured_img = self.soup.find('img', class_='wp-post-image')
        if featured_img and featured_img.get('src'):
            url = featured_img['src']
            if url not in urls:
                urls.append(url)
        
        # Возвращаем через запятую без пробелов
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/ryouri_click
    recipes_dir = os.path.join("preprocessed", "ryouri_click")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RyouriClickExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ryouri_click.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
