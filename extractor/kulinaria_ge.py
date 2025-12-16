"""
Экстрактор данных рецептов для сайта kulinaria.ge
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

# Константа для преобразования дробей в десятичные значения
FRACTION_MAP = {
    '½': 0.5, '¼': 0.25, '¾': 0.75,
    '⅓': 0.3333, '⅔': 0.6667, '⅛': 0.125,
    '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
    '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8
}


class KulinariaGeExtractor(BaseRecipeExtractor):
    """Экстрактор для kulinaria.ge"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с текстом "minutes"
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "N minutes", например "90 minutes" или None
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                
                json_str = script.string
                
                # HTML на kulinaria.ge содержит JSON-LD с неэкранированными переносами строк
                # Используем strict=False для их обработки
                try:
                    decoder = json.JSONDecoder(strict=False)
                    data = decoder.decode(json_str)
                    
                    # Проверяем, является ли это Recipe
                    if isinstance(data, dict) and data.get('@type') == 'Recipe':
                        return data
                except json.JSONDecodeError:
                    # Если не удалось, пропускаем этот script
                    continue
                    
            except (KeyError, AttributeError, TypeError) as e:
                # Логируем ошибку, но продолжаем
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке H1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'description' in json_ld and json_ld['description']:
            return self.clean_text(json_ld['description'])
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc:
                return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc:
                return desc
        
        # Ищем div с классом post__description
        desc_div = self.soup.find('div', class_='post__description')
        if desc_div:
            desc = self.clean_text(desc_div.get_text())
            if desc:
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем извлечь из HTML (более структурированно)
        # Ищем список ингредиентов в div с классом list
        list_container = self.soup.find('div', class_='list')
        
        if list_container:
            items = list_container.find_all('div', class_='list__item')
            
            for item in items:
                # Извлекаем количество, единицу и название отдельно из HTML структуры
                # Структура: <div class="list__item">
                #   <div class="list--sprite"></div>
                #   число (или дробь в sup/sub)
                #   единица
                #   название
                # </div>
                
                # Получаем весь текст
                full_text = item.get_text(separator=' ', strip=True)
                # Нормализуем пробелы (убираем лишние пробелы, переносы строк)
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                
                # Обрабатываем дроби в формате sup/sub (например: <sup>1</sup>⁄<sub>2</sub>)
                # Ищем паттерн: число перед ⁄, потом число после
                # Паттерн фракций: "1 ⁄ 2" или просто Unicode дроби
                
                # Обрабатываем фракции в тексте, используя глобальную константу
                for frac_char, frac_val in FRACTION_MAP.items():
                    if frac_char in full_text:
                        full_text = full_text.replace(frac_char, str(frac_val))
                
                # Паттерн: "1 ⁄ 2 ჩ/კ მარილი" -> нужно вычислить дробь
                # Также обрабатываем случай когда весь текст - это просто дробь + остальное
                frac_match = re.match(r'^(\d+)\s*⁄\s*(\d+)\s+(.+)$', full_text)
                if frac_match:
                    numerator = float(frac_match.group(1))
                    denominator = float(frac_match.group(2))
                    amount = numerator / denominator
                    rest = frac_match.group(3)
                    parts = rest.split(maxsplit=1)
                    unit = parts[0] if parts else None
                    name = parts[1] if len(parts) > 1 else rest
                    
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
                    continue
                
                # Также проверяем паттерн с числом перед дробью: "2 1⁄2 ჩ/კ მარილი"
                mixed_frac_match = re.match(r'^(\d+)\s+(\d+)\s*⁄\s*(\d+)\s+(.+)$', full_text)
                if mixed_frac_match:
                    whole = float(mixed_frac_match.group(1))
                    numerator = float(mixed_frac_match.group(2))
                    denominator = float(mixed_frac_match.group(3))
                    amount = whole + (numerator / denominator)
                    rest = mixed_frac_match.group(4)
                    parts = rest.split(maxsplit=1)
                    unit = parts[0] if parts else None
                    name = parts[1] if len(parts) > 1 else rest
                    
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
                    continue
                
                # Обычный паттерн: "число единица название"
                parts = full_text.split()
                amount = None
                unit = None
                name = full_text
                
                if len(parts) >= 3:
                    # Формат: "число единица название"
                    try:
                        amount = float(parts[0])
                        unit = parts[1]
                        name = ' '.join(parts[2:])
                    except ValueError:
                        # Не число, значит формат другой
                        name = full_text
                elif len(parts) >= 1:
                    # Может быть только название
                    name = full_text
                
                ingredient_dict = {
                    "name": name,
                    "units": unit,
                    "amount": amount
                }
                ingredients.append(ingredient_dict)
        
        # Если HTML не дал результатов, пробуем JSON-LD
        if not ingredients:
            json_ld = self.extract_json_ld()
            if json_ld and 'recipeIngredient' in json_ld:
                for ing_text in json_ld['recipeIngredient']:
                    ing_text = self.clean_text(ing_text)
                    # Пробуем распарсить: "количество единица название"
                    parts = ing_text.split(maxsplit=2)
                    
                    amount = None
                    unit = None
                    name = ing_text
                    
                    if len(parts) >= 3:
                        try:
                            amount = float(parts[0])
                            unit = parts[1]
                            name = parts[2]
                        except ValueError:
                            name = ing_text
                    elif len(parts) == 2:
                        try:
                            amount = float(parts[0])
                            name = parts[1]
                        except ValueError:
                            name = ing_text
                    
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из HTML (более структурированно)
        line_list = self.soup.find('div', class_='lineList')
        
        if line_list:
            items = line_list.find_all('div', class_='lineList__item')
            
            for item in items:
                # Извлекаем текст параграфа (пропускаем div с номером)
                p = item.find('p')
                if p:
                    step_text = self.clean_text(p.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Если HTML не дал результатов, пробуем JSON-LD
        if not steps:
            json_ld = self.extract_json_ld()
            if json_ld and 'recipeInstructions' in json_ld:
                instructions = json_ld['recipeInstructions']
                if isinstance(instructions, str):
                    # Разбиваем на шаги по номерам
                    # Формат: "\n1. шаг1\n2. шаг2\n3. шаг3"
                    parts = instructions.split('\n')
                    for part in parts:
                        part = self.clean_text(part)
                        # Пропускаем пустые строки и строки начинающиеся с "0."
                        # (иногда в JSON-LD могут быть ошибочные шаги с номером 0)
                        if part and not part.startswith('0.'):
                            # Убираем номер в начале, если есть
                            part = re.sub(r'^\d+\.\s*', '', part)
                            if part:
                                steps.append(part)
        
        # Возвращаем как JSON список строк
        return json.dumps(steps, ensure_ascii=False) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На kulinaria.ge обычно нет информации о питательности
        # Можно попробовать найти в JSON-LD, если есть
        json_ld = self.extract_json_ld()
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_match = re.search(r'(\d+)', str(nutrition['proteinContent']))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_match = re.search(r'(\d+)', str(nutrition['fatContent']))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_match = re.search(r'(\d+)', str(nutrition['carbohydrateContent']))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем: "202 kcal; 2/11/27"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках (pagination)
        breadcrumbs = self.soup.find('div', class_='pagination')
        if breadcrumbs:
            links = breadcrumbs.find_all('a', class_='pagination__item')
            # Берем категорию из breadcrumb
            # Обычно структура: Главная > Рецепты > Категория > Подкатегория
            # Пропускаем первые два пункта (Главная, Рецепты) и берем первую реальную категорию
            if len(links) > 2:  # Есть минимум одна категория после "Главная" и "Рецепты"
                # Берем третий элемент (индекс 2) - это первая категория после "Рецепты"
                category = links[2]
                return self.clean_text(category.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На kulinaria.ge обычно есть только cookTime
        # Но можем попробовать найти prepTime в JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'cookTime' in json_ld:
            cook_time = self.parse_iso_duration(json_ld['cookTime'])
            if cook_time:
                return cook_time
        
        # Также можно попробовать найти в HTML
        # Ищем в lineDesc с иконкой времени
        line_desc = self.soup.find('div', class_='lineDesc')
        if line_desc:
            time_div = line_desc.find('div', class_='kulinaria-sprite--time')
            if time_div and time_div.parent:
                time_text = time_div.parent.get_text(strip=True)
                # Формат может быть "0:30:00" или "00:30:00"
                time_match = re.search(r'(\d+):(\d+):(\d+)', time_text)
                if time_match:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    total_minutes = hours * 60 + minutes
                    if total_minutes > 0:
                        return f"{total_minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self.extract_json_ld()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На kulinaria.ge обычно нет отдельной секции с заметками
        # Но можем попробовать найти дополнительную информацию
        
        # Ищем секцию с тегами "როგორ" (как)
        howto_tag = self.soup.find('div', class_='howto-tag')
        if howto_tag:
            notes = self.clean_text(howto_tag.get_text())
            if notes:
                return notes
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Ищем теги в div.howto-tag
        tag_container = self.soup.find('div', class_='howto-tag')
        if tag_container:
            # Ищем ссылки или элементы с тегами
            tag_links = tag_container.find_all('a')
            if tag_links:
                tags_list = []
                for link in tag_links:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags_list.append(tag_text.lower())
                
                if tags_list:
                    # Удаляем дубликаты, сохраняя порядок
                    seen = set()
                    unique_tags = []
                    for tag in tags_list:
                        if tag not in seen:
                            seen.add(tag)
                            unique_tags.append(tag)
                    
                    return ', '.join(unique_tags)
        
        # Также проверяем meta keywords если есть
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
            if tags_list:
                return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Если URL относительный, добавляем домен
            if url.startswith('/'):
                url = f"https://kulinaria.ge{url}"
            urls.append(url)
        
        # 2. Ищем в JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
        
        # 3. Ищем в div.post__img
        post_img = self.soup.find('div', class_='post__img')
        if post_img:
            img_tag = post_img.find('img')
            if img_tag and img_tag.get('src'):
                url = img_tag['src']
                if url.startswith('/'):
                    url = f"https://kulinaria.ge{url}"
                urls.append(url)
        
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
            "ingredient": self.extract_ingredients(),
            "step_by_step": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
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
    # Определяем путь к директории с примерами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "kulinaria_ge"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(KulinariaGeExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python kulinaria_ge.py")


if __name__ == "__main__":
    main()
