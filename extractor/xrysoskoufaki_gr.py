"""
Экстрактор данных рецептов для сайта xrysoskoufaki.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class XrysoskoufakiExtractor(BaseRecipeExtractor):
    """Экстрактор для xrysoskoufaki.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='entry-title')
        if recipe_header:
            title = self.clean_text(recipe_header.get_text())
            # Если есть двоеточие, берем только часть до двоеточия (основное название)
            if ':' in title:
                title = title.split(':')[0].strip()
            return title
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') in ['Article', 'BlogPosting'] or \
                           (isinstance(item.get('@type'), list) and 'Article' in item.get('@type', [])):
                            if 'headline' in item:
                                headline = self.clean_text(item['headline'])
                                # Если есть двоеточие, берем только часть до двоеточия
                                if ':' in headline:
                                    headline = headline.split(':')[0].strip()
                                return headline
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф с большим размером шрифта после заголовка
        # Обычно это описание/анонс рецепта
        content_div = self.soup.find('div', class_='td-post-content')
        if content_div:
            # Ищем параграфы с большим размером шрифта (обычно 20px для описания)
            paragraphs = content_div.find_all('p', style=re.compile(r'font-size:\s*20px', re.I))
            if paragraphs:
                # Берем первый найденный параграф
                desc_text = paragraphs[0].get_text(separator=' ', strip=True)
                return self.clean_text(desc_text)
            
            # Если не нашли по стилю, берем первый обычный параграф
            first_p = content_div.find('p')
            if first_p:
                desc_text = first_p.get_text(separator=' ', strip=True)
                # Пропускаем очень короткие описания
                if len(desc_text) > 20:
                    return self.clean_text(desc_text)
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Dict[str, any]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "2 ποτήρια Ελαιόλαδο" или "500 γρ. Σιμιγδάλι ψιλό"
            
        Returns:
            dict: {"name": "...", "units": "...", "amount": ...}
        """
        text = self.clean_text(text)
        if not text:
            return {"name": text, "units": None, "amount": None}
        
        # Греческие единицы измерения (без внешних скобок, чтобы не создавать группу)
        units_pattern = r'(?:ποτήρι(?:α)?|φλιτζάνι(?:α)?|κούπ(?:α|ες)?|φλ\.|κ\.σ\.|κ\.γ\.|γρ\.|κιλό|λίτρ(?:α|ο)|ml|kg|g|τεμάχι(?:α)?|φέτ(?:α|ες)|κλωνάρι(?:α)?|δέσμη)'
        
        # Попробуем найти паттерн: число + единица + название
        # Примеры: "2 ποτήρια Ελαιόλαδο", "500 γρ. Σιμιγδάλι", "1 κ.γ. Κανέλα"
        pattern = r'^([\d\s/.,–-]+)\s*(' + units_pattern + r')?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            groups = match.groups()
            amount_str = groups[0] if len(groups) > 0 else None
            unit = groups[1] if len(groups) > 1 else None
            name = groups[2] if len(groups) > 2 else text
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                # Обработка диапазонов типа "1-1,2" или "1–1,2"
                if '–' in amount_str or '-' in amount_str:
                    amount = amount_str  # Оставляем как строку для диапазонов
                elif '/' in amount_str:
                    # Обработка дробей
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    # Конвертируем в int если это целое число
                    if total == int(total):
                        amount = int(total)
                    else:
                        amount = total
                else:
                    try:
                        val = float(amount_str)
                        # Конвертируем в int если это целое число
                        if val == int(val):
                            amount = int(val)
                        else:
                            amount = val
                    except ValueError:
                        amount = amount_str
            
            # Очистка названия
            name = self.clean_text(name) if name else text
            # Удаляем фразы в скобках
            name = re.sub(r'\([^)]*\)', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name if name else text,
                "units": unit.strip() if unit else None,
                "amount": amount
            }
        
        # Если паттерн не совпал, просто возвращаем название
        return {"name": text, "units": None, "amount": None}
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        content_div = self.soup.find('div', class_='td-post-content')
        if not content_div:
            return None
        
        # Ищем заголовок "Υλικά" или "Ingredients"
        ingredient_headings = content_div.find_all(['h2', 'h3', 'h4'], 
                                                   string=lambda s: s and ('Υλικά' in s or 'Ingredients' in s))
        
        if not ingredient_headings:
            return None
        
        heading = ingredient_headings[0]
        
        # Извлекаем ингредиенты из следующих элементов до следующего основного заголовка
        current = heading.find_next_sibling()
        
        while current:
            # Останавливаемся на следующем основном заголовке (Εκτέλεση, Instructions и т.д.)
            if current.name in ['h2', 'h3']:
                text = current.get_text(strip=True)
                if any(word in text for word in ['Εκτέλεση', 'Instructions', 'Προετοιμασία']):
                    break
            
            # Извлекаем ингредиенты из <p> с <br> разделителями
            if current.name == 'p':
                # Проверяем, не является ли это подзаголовком (ζύμης:, γέμισης: и т.д.)
                p_text = current.get_text(strip=True)
                
                # Пропускаем короткие параграфы-заголовки
                if len(p_text) < 50 and p_text.endswith(':'):
                    current = current.find_next_sibling()
                    continue
                
                # Разбиваем по <br> тегам
                for br in current.find_all('br'):
                    br.replace_with('\n')
                
                # Извлекаем текст и разбиваем на строки
                lines = current.get_text().split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    # Пропускаем пустые строки и подзаголовки
                    if not line or len(line) < 3:
                        continue
                    if line.endswith(':') and len(line) < 30:
                        continue
                    
                    # Парсим ингредиент
                    parsed = self.parse_ingredient_text(line)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
            
            # Извлекаем ингредиенты из <ul> списков (для файлов с подзаголовками типа "Για τον ζωμό:")
            elif current.name == 'ul':
                li_elements = current.find_all('li')
                for li in li_elements:
                    ingredient_text = li.get_text(separator=' ', strip=True)
                    
                    # Пропускаем слишком короткие или заголовки
                    if len(ingredient_text) < 3 or ingredient_text.endswith(':'):
                        continue
                    
                    # Парсим ингредиент
                    parsed = self.parse_ingredient_text(ingredient_text)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
            
            # Пропускаем подзаголовки <h4> (Για τον ζωμό:, Για τη σούπα: и т.д.)
            elif current.name == 'h4':
                pass
            
            current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию "Εκτέλεση" (Execution/Instructions)
        content_div = self.soup.find('div', class_='td-post-content')
        if not content_div:
            return None
        
        # Находим заголовок "Εκτέλεση" или "Instructions" (может быть h2, h3 или h4)
        headings = content_div.find_all(['h2', 'h3', 'h4'], 
                                       string=lambda s: s and ('Εκτέλεση' in s or 'Instructions' in s))
        
        if not headings:
            return None
        
        # Берем первый найденный заголовок
        heading = headings[0]
        
        # Извлекаем все последующие элементы до следующего основного заголовка
        current = heading.find_next_sibling()
        step_number = 1
        
        while current:
            # Останавливаемся на следующем основном заголовке h2 или h3
            if current.name in ['h2', 'h3']:
                break
            
            # Обрабатываем нумерованные подзаголовки h4 (формат: "1.Название шага")
            if current.name == 'h4':
                h4_text = current.get_text(strip=True)
                
                # Проверяем, начинается ли с номера
                if re.match(r'^\d+\.', h4_text):
                    # Извлекаем следующий параграф как текст шага
                    next_p = current.find_next_sibling('p')
                    if next_p:
                        step_text = next_p.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        if step_text and len(step_text) > 10:
                            # Добавляем шаг с номером из h4 (опционально можно добавить название из h4)
                            steps.append(step_text)
                            step_number += 1
            
            # Обрабатываем обычные параграфы с инструкциями
            elif current.name == 'p':
                # Пропускаем параграфы, которые уже были обработаны как часть h4
                # Проверяем, есть ли предыдущий h4 брат
                prev_sibling = current.find_previous_sibling()
                if prev_sibling and prev_sibling.name == 'h4' and re.match(r'^\d+\.', prev_sibling.get_text(strip=True)):
                    # Этот параграф уже был обработан как часть h4
                    current = current.find_next_sibling()
                    continue
                
                # Извлекаем текст шага
                step_text = current.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                # Пропускаем короткие параграфы и изображения
                if step_text and len(step_text) > 10:
                    steps.append(step_text)
            
            current = current.find_next_sibling()
        
        if not steps:
            return None
        
        # Нумеруем шаги, если они еще не пронумерованы
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps)
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем категории в <li class="entry-category">
        categories = []
        category_items = self.soup.find_all('li', class_='entry-category')
        
        for item in category_items:
            link = item.find('a')
            if link:
                cat_text = self.clean_text(link.get_text())
                if cat_text and cat_text not in ['Συνταγές Μαγειρικής']:  # Пропускаем общую категорию
                    categories.append(cat_text)
        
        if categories:
            # Берем последнюю (самую специфичную) категорию
            category_name = categories[-1] if len(categories) > 0 else categories[0]
            
            # Маппинг греческих категорий на английские
            category_mapping = {
                'Γλυκά - Παγωτά': 'Dessert',
                'Γλυκά': 'Dessert',
                'Παγωτά': 'Dessert',
                'Ορεκτικά': 'Appetizer',
                'Κυρίως Πιάτα': 'Main Course',
                'Κυρίως': 'Main Course',
                'Σαλάτες': 'Salad',
                'Σούπες': 'Soup',
                'Ζυμαρικά': 'Pasta',
                'Πίτες': 'Pie',
            }
            
            return category_mapping.get(category_name, category_name)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в <ul class="td-tags">
        tags_container = self.soup.find('ul', class_='td-tags')
        if tags_container:
            tag_items = tags_container.find_all('li')
            for item in tag_items:
                link = item.find('a')
                if link:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags.append(tag_text)
        
        # Альтернативно - из JSON-LD
        if not tags:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if '@graph' in data:
                        for item in data['@graph']:
                            if 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags.extend(keywords)
                                elif isinstance(keywords, str):
                                    tags.extend([k.strip() for k in keywords.split(',') if k.strip()])
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return ', '.join(tags) if tags else None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста по типу
        
        Args:
            time_type: 'prep', 'cook' или 'total'
        """
        content_div = self.soup.find('div', class_='td-post-content')
        if not content_div:
            return None
        
        # Сначала пробуем найти время в структурированных span элементах (новый формат)
        # Ищем все span.mv-time-minutes
        time_spans = content_div.find_all('span', class_='mv-time-minutes')
        if time_spans and len(time_spans) >= 3:
            # Обычно порядок: prep, cook, total
            time_map = {
                'prep': 0,
                'cook': 1,
                'total': 2
            }
            idx = time_map.get(time_type)
            if idx is not None and idx < len(time_spans):
                time_text = time_spans[idx].get_text(strip=True)
                # Текст уже в формате "10 minutes"
                return time_text
        
        # Если не нашли в span, ищем в тексте по греческим меткам
        # Греческие названия типов времени
        time_labels = {
            'prep': [r'Χρόνος\s+Προετοιμασίας', r'Preparation\s+Time'],
            'cook': [r'Χρόνος\s+Μαγειρέματος', r'Χρόνος\s+Ψησίματος', r'Cook(?:ing)?\s+Time'],
            'total': [r'Συνολικός\s+Χρόνος', r'Total\s+Time']
        }
        
        labels = time_labels.get(time_type, [])
        text = content_div.get_text()
        
        # Ищем паттерн: "[Label]: [Number] [Unit]"
        for label in labels:
            # Паттерн: "Χρόνος Προετοιμασίας: 20 λεπτά" или "Prep Time: 20 minutes"
            pattern = label + r':\s*(\d+)\s*(λεπτ[άα]|ώρ[αες]|min(?:ute)?s?|hour?s?)'
            match = re.search(pattern, text, re.IGNORECASE)
            
            if match:
                num = match.group(1)
                unit = match.group(2)
                
                # Конвертируем в минуты
                if 'λεπτ' in unit or 'min' in unit.lower():
                    return f"{num} minutes"
                elif 'ώρ' in unit or 'hour' in unit.lower():
                    return f"{int(num) * 60} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_text('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию с заметками/советами после основного контента
        content_div = self.soup.find('div', class_='td-post-content')
        if content_div:
            # Ищем заголовки с "Tips", "Σημειώσεις", "Συμβουλές" и т.д.
            headings = content_div.find_all(['h2', 'h3', 'h4'], 
                                           string=re.compile(r'(Tips|Σημειώσεις|Συμβουλές|Χρήσιμα)', re.I))
            
            for heading in headings:
                # Извлекаем параграфы после заголовка
                current = heading.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3', 'h4']:
                        break
                    
                    if current.name == 'p':
                        note_text = current.get_text(separator=' ', strip=True)
                        note_text = self.clean_text(note_text)
                        if note_text and len(note_text) > 10:
                            notes.append(note_text)
                    
                    current = current.find_next_sibling()
                
                if notes:
                    break
        
        return ' '.join(notes) if notes else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        # Ищем изображение в Article/BlogPosting
                        if 'image' in item:
                            img = item['image']
                            if isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
                            elif isinstance(img, str):
                                urls.append(img)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки HTML-файлов"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "xrysoskoufaki_gr")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(XrysoskoufakiExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python xrysoskoufaki_gr.py")


if __name__ == "__main__":
    main()
