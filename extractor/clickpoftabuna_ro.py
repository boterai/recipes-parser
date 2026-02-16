"""
Экстрактор данных рецептов для сайта clickpoftabuna.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ClickPoftabunaExtractor(BaseRecipeExtractor):
    """Экстрактор для clickpoftabuna.ro"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            return self.clean_text(title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Берем только первое предложение (до первой точки или "…")
            if '. ' in desc:
                desc = desc.split('. ')[0] + '.'
            elif '…' in desc:
                desc = desc.split('…')[0] + '.'
            return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if '. ' in desc:
                desc = desc.split('. ')[0] + '.'
            elif '…' in desc:
                desc = desc.split('…')[0] + '.'
            return desc
        
        # Первый параграф после h1
        h1 = self.soup.find('h1')
        if h1:
            # Ищем первый параграф после h1
            for sibling in h1.find_next_siblings():
                if sibling.name == 'p':
                    text = self.clean_text(sibling.get_text())
                    if text and len(text) > 20 and 'ingredient' not in text.lower():
                        if '. ' in text:
                            text = text.split('. ')[0] + '.'
                        elif '…' in text:
                            text = text.split('…')[0] + '.'
                        return text
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Находим параграф с текстом "De ce ai nevoie" или "Ingrediente"
        paras = self.soup.find_all('p')
        
        for para in paras:
            text = para.get_text().strip()
            
            # Ищем параграф с ингредиентами
            if 'de ce ai nevoie' in text.lower() or text.lower() == 'ingrediente':
                # Разбиваем текст по переносам строк
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    # Пропускаем заголовок
                    if 'de ce ai nevoie' in line.lower() or line.lower() == 'ingrediente':
                        continue
                    
                    # Убираем "- " в начале
                    if line.startswith('-'):
                        line = line[1:].strip()
                    
                    # Если строка содержит несколько ингредиентов через запятую (например "sare, piper, chilli")
                    if ',' in line and not any(char.isdigit() for char in line):
                        # Разделяем по запятым
                        for ingredient in line.split(','):
                            ingredient = ingredient.strip()
                            if ingredient:
                                parsed = self.parse_ingredient(ingredient)
                                if parsed:
                                    ingredients.append(parsed)
                    elif line and len(line) > 2:
                        # Парсим ингредиент
                        parsed = self.parse_ingredient(line)
                        if parsed:
                            ingredients.append(parsed)
                
                # Если нашли ингредиенты, выходим
                if ingredients:
                    break
            
            # Также проверяем построчный формат (как в салате)
            if text.lower() == 'ingrediente':
                # Следующие параграфы - ингредиенты
                idx = paras.index(para)
                for next_para in paras[idx+1:]:
                    next_text = next_para.get_text().strip()
                    # Конец секции ингредиентов
                    if next_text.lower() in ['mod de preparare', 'preparare', 'instrucțiuni'] or len(next_text) > 100:
                        break
                    
                    if next_text and len(next_text) > 2:
                        parsed = self.parse_ingredient(next_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 g de ravioli al funghi" или "6 cartofi"
            
        Returns:
            dict: {"name": "ravioli al funghi", "amount": "250", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
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
        # Примеры: "250 g de ravioli", "2 linguri muștar", "1 ceapă roșie"
        # Важно: более длинные единицы должны быть первыми, чтобы "linguri" не матчилось как "l"
        pattern = r'^([\d\s/.,]+)?\s*(lingurițe?|linguriță|lingură|linguri?|litri?|bucăți?|căței|frunze|capere|felii?|fir(?:e)?|buc|kg|ml|g|l)?\s*(?:de\s+)?(.+)'
        
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
                amount = total  # Оставляем как число
            else:
                # Пробуем преобразовать в число
                try:
                    amount = int(amount_str.replace(',', '.')) if '.' not in amount_str else float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "după gust", "opțional", и т.д.
        name = re.sub(r'\b(după gust|opțional|pentru decor|pentru servire)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit  # Используем "units" (plural) как в expected
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Находим параграфы с инструкциями
        paras = self.soup.find_all('p')
        
        # Сначала ищем параграф с "De ce ai nevoie" и берем следующие параграфы как инструкции
        for i, para in enumerate(paras):
            text = para.get_text().strip()
            
            # Если это параграф с ингредиентами, следующий параграф - инструкции
            if 'de ce ai nevoie' in text.lower():
                # Берем следующие параграфы
                for j in range(i+1, len(paras)):
                    next_text = paras[j].get_text().strip()
                    
                    # Пропускаем пустые и служебные параграфы
                    if not next_text or len(next_text) < 10:
                        continue
                    
                    # Пропускаем параграфы с "Află de AICI"
                    if 'află de aici' in next_text.lower() or 'află aici' in next_text.lower():
                        continue
                    
                    # Пропускаем длинные параграфы (скорее всего футер)
                    if len(next_text) > 500 or 'utilizarea profilurilor' in next_text.lower():
                        break
                    
                    step_text = self.clean_text(next_text)
                    if step_text:
                        steps.append(step_text)
                
                break
            
            # Также проверяем формат "Mod de preparare"
            if text.lower() in ['mod de preparare', 'preparare', 'instrucțiuni']:
                # Берем следующие параграфы
                for j in range(i+1, len(paras)):
                    next_text = paras[j].get_text().strip()
                    
                    # Пропускаем пустые
                    if not next_text or len(next_text) < 10:
                        continue
                    
                    # Пропускаем параграфы с "Află de AICI"
                    if 'află de aici' in next_text.lower():
                        continue
                    
                    # Пропускаем длинные параграфы футера
                    if len(next_text) > 500 or 'utilizarea profilurilor' in next_text.lower():
                        break
                    
                    step_text = self.clean_text(next_text)
                    if step_text:
                        steps.append(step_text)
                
                break
        
        # Объединяем все шаги в одну строку через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках через JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем BreadcrumbList
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            elements = item.get('itemListElement', [])
                            # Берем предпоследний элемент (последний - это сама страница)
                            if len(elements) >= 2:
                                category_item = elements[-2]
                                if 'item' in category_item and 'name' in category_item['item']:
                                    category = category_item['item']['name']
                                    # Преобразуем в английский или оставляем как есть
                                    if 'legume' in category.lower():
                                        return None
                                    return self.clean_text(category)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте clickpoftabuna.ro время подготовки не указывается явно
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания времени
        paras = self.soup.find_all('p')
        
        times = []
        for para in paras:
            text = para.get_text()
            # Ищем паттерны типа "20 de minute", "25 minutes", "1 oră"
            time_matches = re.findall(r'(\d+)\s+(de\s+)?(minute?|minut|ore|oră|hour|hours)', text, re.IGNORECASE)
            for match in time_matches:
                number = int(match[0])
                unit = match[2].lower()
                if 'minut' in unit or 'minute' in unit:
                    times.append(number)  # в минутах
                elif 'oră' in unit or 'ore' in unit or 'hour' in unit:
                    times.append(number * 60)  # конвертируем часы в минуты
        
        # Берем максимальное время (обычно это основное время готовки)
        if times:
            max_time = max(times)
            return f"{max_time} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте clickpoftabuna.ro общее время не указывается явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На сайте clickpoftabuna.ro заметки обычно не указываются
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Преобразуем в формат тегов (через запятую с пробелом)
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            
            # Попробуем также извлечь из JSON-LD
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                article_keywords = item['keywords']
                                if isinstance(article_keywords, list):
                                    tags.extend(article_keywords)
                                elif isinstance(article_keywords, str):
                                    tags.extend([k.strip() for k in article_keywords.split(',') if k.strip()])
                except (json.JSONDecodeError, KeyError):
                    continue
            
            # Удаляем дубликаты
            unique_tags = []
            seen = set()
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # Article с image
                        if item.get('@type') == 'Article' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                        
                        # ImageObject
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Проверяем, что url - строка
                if isinstance(url, str) and url and url not in seen:
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/clickpoftabuna_ro
    recipes_dir = os.path.join("preprocessed", "clickpoftabuna_ro")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ClickPoftabunaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python clickpoftabuna_ro.py")


if __name__ == "__main__":
    main()
