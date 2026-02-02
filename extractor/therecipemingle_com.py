"""
Экстрактор данных рецептов для сайта therecipemingle.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TheRecipeMingleExtractor(BaseRecipeExtractor):
    """Экстрактор для therecipemingle.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем суффиксы типа " (a.k.a. ...)"
            name = re.sub(r'\s*\([^)]*\)', '', name)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы сайта
            title = re.sub(r'\s*[-–]\s*The recipe mingle.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\([^)]*\)', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
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
        
        # Ищем все списки на странице
        lists = self.soup.find_all(['ul', 'ol'])
        
        # Находим список ингредиентов (обычно это первый ul список с элементами, начинающимися с чисел/количеств)
        for lst in lists:
            items = lst.find_all('li', recursive=False)
            
            # Проверяем, похож ли это список на ингредиенты
            # Ингредиенты обычно начинаются с количества (число или дробь)
            if len(items) >= 3:
                first_text = items[0].get_text(strip=True)
                # Проверяем, начинается ли с числа или дроби
                # И это должен быть ul список (не ol)
                if lst.name == 'ul' and re.match(r'^[\d½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]', first_text):
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        # Убираем текст после "–" или "—" (это обычно описание)
                        ingredient_text = re.split(r'[–—]', ingredient_text)[0]
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим в структурированный формат
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    if ingredients:
                        break
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на десятичные числа
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        # Важно: единица должна быть целым словом, а не просто "g" из начала слова
        pattern = r'^([\d\s/.,]+)?\s*\b(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz\b|grams?|kilograms?|kg|ml|milliliters?|liters?|large|medium|small|pinch(?:es)?|dash(?:es)?|packages?|pkg|box(?:es)?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)\b\s*(?:\([^)]+\))?\s*(.+)'
        
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
                        try:
                            total += float(part)
                        except:
                            pass
                amount = total if total > 0 else None
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except:
                    amount = None
        
        # Обработка единицы измерения
        # Фильтруем случаи когда "large" и подобные были захвачены как unit
        if unit:
            unit = unit.strip()
            # Если это "large", "medium", "small" - это часть названия, а не единица
            if unit.lower() in ['large', 'medium', 'small', 'lge', 'med', 'sm', 'larg', 'arge']:
                # Добавляем обратно к названию
                name = unit + ' ' + name
                unit = None
        else:
            unit = None
        
        # Очистка названия
        # Удаляем скобки с содержимым (уже удалены в паттерне)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|softened|room temperature)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые в конце
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s*,\s*$', '', name)  # Убираем запятые в конце с пробелами
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все списки на странице
        lists = self.soup.find_all(['ul', 'ol'])
        
        # Сначала пробуем найти ol список (предпочтительнее для инструкций)
        # Затем ищем ul список, который выглядит как инструкции
        for lst in lists:
            items = lst.find_all('li', recursive=False)
            
            # Инструкции должны содержать команды и не быть ингредиентами
            if len(items) >= 3:
                # Проверяем первый элемент - не должен начинаться с числа (как ингредиент)
                first_text = items[0].get_text(strip=True)
                
                # Если начинается с числа/дроби - это скорее ингредиенты, пропускаем
                if re.match(r'^[\d½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]', first_text):
                    continue
                
                # Проверяем, содержит ли список глаголы действия
                sample_text = ' '.join([item.get_text(strip=True)[:100] for item in items[:2]])
                has_verbs = any(word in sample_text.lower() for word in ['mix', 'add', 'bake', 'stir', 'combine', 'preheat', 'cream', 'beat', 'whisk', 'blend', 'roll', 'coat', 'place', 'line'])
                
                # Также проверяем средниюю длину - инструкции обычно длиннее
                avg_length = sum(len(item.get_text(strip=True)) for item in items[:3]) / min(3, len(items))
                
                if has_verbs and avg_length > 40:
                    for idx, item in enumerate(items, 1):
                        step_text = item.get_text(separator=' ', strip=True)
                        
                        # Извлекаем текст, убирая заголовки в начале вида "Title:"
                        parts = step_text.split(':', 1)
                        if len(parts) == 2 and len(parts[0]) < 50 and not any(c.isdigit() for c in parts[0][:10]):
                            # Первая часть - заголовок (если там нет цифр в начале), вторая - инструкция
                            step_text = parts[1].strip()
                        
                        step_text = self.clean_text(step_text)
                        
                        if step_text:
                            steps.append(f"{idx}. {step_text}")
                    
                    if steps:
                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return sections[0]
                            elif isinstance(sections, str):
                                return sections
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно ищем в ссылках категорий
        category_link = self.soup.find('a', rel='category tag')
        if category_link:
            return self.clean_text(category_link.get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Получаем весь текст страницы
        text_content = self.soup.get_text()
        
        # Паттерны для поиска
        patterns = {
            'prep': [r'prep[^.]*?(\d+\s*(?:minutes?|hours?))', r'preparation[^.]*?(\d+\s*(?:minutes?|hours?))'],
            'cook': [r'cook[^.]*?(\d+\s*(?:minutes?|hours?))', r'baking?[^.]*?(\d+\s*(?:minutes?|hours?))'],
            'total': [r'total[^.]*?(\d+\s*(?:minutes?|hours?))', r'ready\s+in[^.]*?(\d+\s*(?:minutes?|hours?))']
        }
        
        if time_type not in patterns:
            return None
        
        for pattern in patterns[time_type]:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            if matches:
                # Возвращаем первое совпадение
                return matches[0]
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после инструкций или в конце рецепта
        # которые могут содержать заметки
        
        # Часто заметки находятся после списка инструкций
        lists = self.soup.find_all(['ul', 'ol'])
        
        for lst in lists:
            # Проверяем, это список инструкций?
            items = lst.find_all('li', recursive=False)
            if len(items) >= 3:
                sample_text = items[0].get_text(strip=True)
                if len(sample_text) > 50:  # Похоже на инструкции
                    # Ищем следующие параграфы
                    next_elem = lst.find_next_sibling(['p', 'div'])
                    if next_elem:
                        text = next_elem.get_text(strip=True)
                        # Проверяем, содержит ли текст типичные фразы для заметок
                        if any(keyword in text.lower() for keyword in ['note', 'tip', 'store', 'freeze', 'keep', 'best']):
                            return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD или мета-тегах
        # Для therecipemingle.com теги могут быть в категориях или явно указаны
        
        # Собираем теги из различных источников
        tags = []
        
        # 1. Категория как тег
        category = self.extract_category()
        if category:
            tags.append(category.lower())
        
        # 2. Ищем ключевые слова в мета-тегах
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = [k.strip().lower() for k in meta_keywords['content'].split(',')]
            tags.extend(keywords)
        
        # 3. Из заголовка можем извлечь ключевые слова
        title = self.extract_dish_name()
        if title:
            # Извлекаем ключевые слова (без стоп-слов)
            title_lower = title.lower()
            for keyword in ['cookie', 'dessert', 'cake', 'pie', 'bread', 'sweet', 'savory']:
                if keyword in title_lower:
                    if keyword not in tags:
                        tags.append(keyword)
        
        if tags:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag not in seen and tag:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image - часто другой размер/вариант
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
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item and item['url'] not in urls:
                                urls.append(item['url'])
                            elif 'contentUrl' in item and item['contentUrl'] not in urls:
                                urls.append(item['contentUrl'])
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
    """Точка входа для обработки HTML-файлов"""
    import os
    
    # Ищем директорию с примерами
    preprocessed_dir = os.path.join("preprocessed", "therecipemingle_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TheRecipeMingleExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python therecipemingle_com.py")


if __name__ == "__main__":
    main()
