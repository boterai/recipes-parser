"""
Экстрактор данных рецептов для сайта foodfromportugal.com
"""

import sys
import re
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodFromPortugalExtractor(BaseRecipeExtractor):
    """Экстрактор для foodfromportugal.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом entry-title
        title_elem = self.soup.find('h1', class_='entry-title')
        if title_elem:
            # Внутри может быть span с itemprop="name"
            span_elem = title_elem.find('span', itemprop='name')
            if span_elem:
                return self.clean_text(span_elem.get_text())
            return self.clean_text(title_elem.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*\|\s*Food From Portugal.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*Receita de\s*', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в div.description внутри entry-content (приоритет)
        desc_div = self.soup.find('div', class_='description')
        if desc_div:
            em_elem = desc_div.find('em')
            if em_elem:
                p_elem = em_elem.find('p')
                if p_elem:
                    return self.clean_text(p_elem.get_text())
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Пример: "100 ml de azeite" -> {name: "azeite", amount: 100, units: "ml"}
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Паттерн для извлечения: количество, единица измерения и название
        # Примеры: "100 ml de azeite", "3 ovos M", "150 g de açúcar", "Raspa de um limão"
        
        # Специальные случаи: "Raspa de um/uma X" -> amount: 1, unit: "unit", name: "raspa de X"
        raspa_match = re.match(r'^Raspa\s+de\s+u[mn]a?\s+(.+)$', text, re.IGNORECASE)
        if raspa_match:
            return {
                "name": "raspa de " + raspa_match.group(1).lower(),
                "amount": 1,
                "units": "unit"
            }
        
        # Попробуем несколько паттернов
        patterns = [
            # Паттерн: число + единица + "de" + название
            r'^(\d+(?:[.,]\d+)?)\s*(ml|g|kg|l|colher de sopa|colher de chá|colheres de sopa|colheres de chá|unidades?|M)?\s*(?:de\s+)?(.+)$',
            # Паттерн: число + название (без единиц)
            r'^(\d+(?:[.,]\d+)?)\s+(.+)$',
            # Паттерн: только название (без количества)
            r'^([^0-9].*)$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                
                if len(groups) == 3:  # Полный паттерн с числом, единицей и названием
                    amount_str, unit, name = groups
                    
                    # Преобразуем количество
                    amount = None
                    if amount_str:
                        amount_str = amount_str.replace(',', '.')
                        try:
                            amount = float(amount_str)
                            # Если целое число, преобразуем к int
                            if amount.is_integer():
                                amount = int(amount)
                        except ValueError:
                            amount = amount_str
                    
                    # Очищаем название
                    name = self.clean_text(name) if name else text
                    # Очищаем единицу измерения
                    unit = unit.strip() if unit else None
                    
                    # Специальный случай для "3 ovos M" -> name: "ovos", unit: "M"
                    if not unit and name and name.endswith(' M'):
                        name = name[:-2].strip()
                        unit = 'M'
                    
                    return {
                        "name": name.lower(),
                        "amount": amount,
                        "units": unit
                    }
                
                elif len(groups) == 2:  # Число + название (без единицы)
                    amount_str, name = groups
                    amount = None
                    try:
                        amount_str = amount_str.replace(',', '.')
                        amount = float(amount_str)
                        if amount.is_integer():
                            amount = int(amount)
                    except (ValueError, AttributeError):
                        # Это не число, значит весь текст - название
                        name = text
                        amount = None
                    
                    return {
                        "name": self.clean_text(name).lower(),
                        "amount": amount,
                        "units": None
                    }
                
                else:  # Только название
                    return {
                        "name": self.clean_text(groups[0]).lower(),
                        "amount": None,
                        "units": None
                    }
        
        # Если ничего не подошло, возвращаем как есть
        return {
            "name": text.lower(),
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients_list = []
        
        # Ищем секцию с ингредиентами
        ingredients_section = self.soup.find('div', class_='shortcode-ingredients')
        if not ingredients_section:
            return None
        
        # Извлекаем элементы списка
        items = ingredients_section.find_all('li')
        
        for item in items:
            # Находим span с itemprop="recipeIngredient"
            ingredient_span = item.find('span', itemprop='recipeIngredient')
            if ingredient_span:
                ingredient_text = ingredient_span.get_text(strip=True)
                parsed = self.parse_ingredient_line(ingredient_text)
                if parsed and parsed.get('name'):
                    ingredients_list.append(parsed)
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с инструкциями
        instructions_section = self.soup.find('div', class_='shortcode-directions')
        if not instructions_section:
            return None
        
        instructions_list = []
        
        # Извлекаем элементы списка (ol > li)
        ol_elem = instructions_section.find('ol')
        if ol_elem:
            items = ol_elem.find_all('li', recursive=False)
            
            for item in items:
                # Находим span с itemprop="recipeInstructions"
                instruction_span = item.find('span', itemprop='recipeInstructions')
                if instruction_span:
                    step_text = instruction_span.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        instructions_list.append(step_text)
        
        if instructions_list:
            # Объединяем все шаги в одну строку
            return ' '.join(instructions_list)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в div с классом category-post
        category_div = self.soup.find('div', class_='category-post')
        if category_div:
            # Внутри есть span с itemprop="recipeCategory"
            span = category_div.find('span', itemprop='recipeCategory')
            if span:
                # Внутри могут быть ссылки
                links = span.find_all('a')
                if links:
                    # Берем первую категорию
                    return self.clean_text(links[0].get_text())
        
        # Альтернативно из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            sections = meta_section['content']
            # Может быть список через запятую, берем первую
            if ',' in sections:
                return self.clean_text(sections.split(',')[0])
            return self.clean_text(sections)
        
        return None
    
    def extract_time(self, time_class: str) -> Optional[str]:
        """
        Извлечение времени из div с определенным классом
        time_class: 'time1' для prep_time, 'time2' для cook_time, 'time3' для total_time
        """
        # Ищем div с нужным классом
        time_div = self.soup.find('div', class_=time_class)
        if time_div:
            # Извлекаем текст
            text = time_div.get_text(separator=' ', strip=True)
            # Убираем префикс типа "T. preparação:", "T. Cozedura:", "T. Total:"
            text = re.sub(r'^T\.\s*\w+\s*:\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            if text:
                # Преобразуем формат, если нужно (например "15m" -> "15 minutes")
                # Но в примерах уже готовый формат, так что просто возвращаем
                text = text.replace('m', ' minutes')
                text = text.replace('h', ' hours')
                text = re.sub(r'\s+', ' ', text).strip()
                return text
        
        # Также пробуем через meta itemprop
        meta_prep = self.soup.find('meta', itemprop='prepTime')
        meta_cook = self.soup.find('meta', itemprop='cookTime')
        meta_total = self.soup.find('meta', itemprop='totalTime')
        
        if time_class == 'time1' and meta_prep:
            return meta_prep.get('content')
        elif time_class == 'time2' and meta_cook:
            return meta_cook.get('content')
        elif time_class == 'time3' and meta_total:
            return meta_total.get('content')
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('time1')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self.extract_time('time2')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('time3')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем заголовок DICAS
        content_div = self.soup.find('div', class_='entry-content')
        if content_div:
            # Ищем заголовок h2 с текстом "DICAS"
            h2_elements = content_div.find_all('h2')
            for h2 in h2_elements:
                h2_text = h2.get_text()
                if 'DICAS' in h2_text.upper() or 'DICA' in h2_text.upper():
                    # Берем все параграфы после этого заголовка до следующего h2
                    notes_parts = []
                    for sibling in h2.find_next_siblings():
                        if sibling.name == 'h2':
                            break
                        if sibling.name == 'p':
                            # Очищаем от номеров типа "1.", "2." и жирного текста
                            text = sibling.get_text(separator=' ', strip=True)
                            # Убираем номера и жирный текст в начале
                            text = re.sub(r'^\d+\.\s*', '', text)
                            text = self.clean_text(text)
                            if text and len(text) > 20:
                                notes_parts.append(text)
                    
                    if notes_parts:
                        return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из различных источников"""
        tags_list = []
        
        # Приоритет: берем теги из category-post (это основные категории рецепта)
        category_div = self.soup.find('div', class_='category-post')
        if category_div:
            span = category_div.find('span', itemprop='recipeCategory')
            if span:
                links = span.find_all('a')
                for link in links:
                    tag = self.clean_text(link.get_text())
                    if tag:
                        tags_list.append(tag.lower())
        
        # Если тегов мало, добавим несколько из JSON-LD keywords
        if len(tags_list) < 5:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    # Если это объект с @graph
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, str):
                                    kw_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                                    # Берем только некоторые релевантные ключевые слова
                                    for kw in kw_list:
                                        if len(tags_list) >= 5:
                                            break
                                        if kw not in tags_list and len(kw) > 3:
                                            tags_list.append(kw)
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        if tags_list:
            # Ограничим до 4-5 тегов
            tags_list = tags_list[:5]
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем главное изображение рецепта
        # Обычно это первое изображение в entry-content
        content_div = self.soup.find('div', class_='entry-content')
        if content_div:
            # Ищем picture или img
            pictures = content_div.find_all('picture', limit=3)
            for picture in pictures:
                img = picture.find('img')
                if img and img.get('src'):
                    # Берем src, но не data-src
                    src = img.get('src')
                    if src and not src.startswith('data:'):
                        if src not in urls:
                            urls.append(src)
                # Также проверяем data-src
                elif img and img.get('data-src'):
                    data_src = img.get('data-src')
                    if data_src and not data_src.startswith('data:') and data_src not in urls:
                        urls.append(data_src)
            
            # Если нет picture, ищем прямые img
            if not urls:
                images = content_div.find_all('img', limit=3)
                for img in images:
                    src = img.get('src')
                    if src and not src.startswith('data:') and src not in urls:
                        urls.append(src)
        
        # 3. Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                # Ищем ImageObject
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                            if 'url' in item and item['url'] not in urls:
                                urls.append(item['url'])
                            elif 'contentUrl' in item and item['contentUrl'] not in urls:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        if urls:
            # Берем первые 3 изображения
            urls = urls[:3]
            # Возвращаем как строку через запятую без пробелов
            return ','.join(urls)
        
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
    """Точка входа для тестирования"""
    import os
    
    # Обрабатываем папку preprocessed/foodfromportugal_com
    preprocessed_dir = os.path.join("preprocessed", "foodfromportugal_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FoodFromPortugalExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python foodfromportugal_com.py")


if __name__ == "__main__":
    main()
