"""
Экстрактор данных рецептов для сайта kikkoman.co.jp (японский сайт рецептов)
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KikkomanExtractor(BaseRecipeExtractor):
    """Экстрактор для kikkoman.co.jp"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h3 с классом ttl-lv3-tsushin (название рецепта)
        recipe_title = self.soup.find('h3', class_='ttl-lv3-tsushin')
        if recipe_title:
            return self.clean_text(recipe_title.get_text())
        
        # Альтернатива - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс "| キッコーマン | ホームクッキング"
            title = re.sub(r'\s*\|\s*キッコーマン.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем описание в div.txt-tsushin (первый параграф после изображения)
        txt_div = self.soup.find('div', class_='txt-tsushin')
        if txt_div:
            paragraphs = txt_div.find_all('p')
            if paragraphs:
                return self.clean_text(paragraphs[0].get_text())
        
        # Fallback: извлекаем из HTML meta tags
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD структурированных данных
        json_ld = self.soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, dict) and 'recipeIngredient' in data:
                    recipe_ingredients = data['recipeIngredient']
                    if isinstance(recipe_ingredients, list):
                        for ingredient_str in recipe_ingredients:
                            # Формат: "豚バラ肉 300g" или "ねぎ 1/2本"
                            ingredient_str = self.clean_text(ingredient_str)
                            # Разделяем на название и количество (последнее слово обычно количество)
                            parts = ingredient_str.split()
                            if len(parts) >= 2:
                                name = ' '.join(parts[:-1])
                                amount = parts[-1]
                            else:
                                name = ingredient_str
                                amount = None
                            
                            if name:
                                ingredients.append({
                                    'name': name,
                                    'amount': amount,
                                    'unit': None
                                })
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        # Если JSON-LD не дал результата, пробуем HTML парсинг
        if not ingredients:
            # Ищем div с классом ingredient-list-tsushin
            ingredient_div = self.soup.find('div', class_='ingredient-list-tsushin')
            if ingredient_div:
                # Извлекаем все dl элементы (ингредиенты)
                for dl in ingredient_div.find_all('dl', recursive=False):
                    # Проверяем, не является ли это группой ингредиентов (A), (B) и т.д.
                    if 'ingredient-set-tsushin' in dl.get('class', []):
                        # Это группа ингредиентов типа (A)
                        # Обрабатываем вложенные dl
                        nested_dls = dl.find('dd').find_all('dl') if dl.find('dd') else []
                        for nested_dl in nested_dls:
                            dt = nested_dl.find('dt')
                            dd = nested_dl.find('dd')
                            if dt and dd:
                                name = self.clean_text(dt.get_text())
                                amount = self.clean_text(dd.get_text())
                                if name:
                                    ingredients.append({
                                        'name': name,
                                        'amount': amount if amount else None,
                                        'unit': None
                                    })
                    else:
                        # Обычный ингредиент
                        dt = dl.find('dt')
                        dd = dl.find('dd')
                        if dt and dd:
                            name = self.clean_text(dt.get_text())
                            amount = self.clean_text(dd.get_text())
                            if name:
                                ingredients.append({
                                    'name': name,
                                    'amount': amount if amount else None,
                                    'unit': None
                                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD структурированных данных
        json_ld = self.soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, dict) and 'recipeInstructions' in data:
                    recipe_instructions = data['recipeInstructions']
                    if isinstance(recipe_instructions, list):
                        for instruction in recipe_instructions:
                            if isinstance(instruction, dict) and 'text' in instruction:
                                step_text = self.clean_text(instruction['text'])
                                if step_text:
                                    steps.append(step_text)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        # Если JSON-LD не дал результата, пробуем HTML парсинг
        if not steps:
            # Ищем div с классом detail-list-tsushin
            detail_div = self.soup.find('div', class_='detail-list-tsushin')
            if detail_div:
                # Извлекаем все dl элементы (шаги)
                for dl in detail_div.find_all('dl', recursive=False):
                    dd = dl.find('dd')
                    if dd:
                        step_text = self.clean_text(dd.get_text())
                        if step_text:
                            steps.append(step_text)
        
        # Добавляем нумерацию
        if steps:
            numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            return ' '.join(numbered_steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: kcal; б/ж/у"""
        kcal = protein = fat = carbs = None
        
        # Сначала пробуем извлечь из JSON-LD (только калории)
        json_ld = self.soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, dict) and 'nutrition' in data:
                    nutrition = data['nutrition']
                    if isinstance(nutrition, dict) and 'calories' in nutrition:
                        calories_str = nutrition['calories']
                        kcal_match = re.search(r'(\d+\.?\d*)kcal', calories_str)
                        if kcal_match:
                            kcal = kcal_match.group(1)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        # Если JSON-LD не дал калории, пробуем из HTML (p.detail-txt-tsushin)
        if not kcal:
            detail_txt = self.soup.find('p', class_='detail-txt-tsushin')
            if detail_txt:
                text = self.clean_text(detail_txt.get_text())
                if text:
                    kcal_match = re.search(r'(\d+\.?\d*)kcal', text)
                    if kcal_match:
                        kcal = kcal_match.group(1)
        
        # Извлекаем БЖУ из recipe-detail-main__overview (для страниц типа search/recipe)
        # Ищем все элементы, у которых класс начинается с recipe-detail-main__overview__item
        overview_items = self.soup.find_all('div', class_=lambda x: x and 'recipe-detail-main__overview__item' in x)
        for item in overview_items:
            label_elem = item.find('span', class_='recipe-detail-main__overview__item__name__label')
            value_elem = item.find('div', class_='recipe-detail-main__overview__item__value')
            
            if label_elem and value_elem:
                label = self.clean_text(label_elem.get_text())
                value_text = self.clean_text(value_elem.get_text())
                
                # Извлекаем числовое значение
                value_match = re.search(r'(\d+\.?\d*)', value_text)
                if value_match:
                    value = value_match.group(1)
                    
                    if 'エネルギー' in label and not kcal:
                        kcal = value
                    elif 'たんぱく質' in label:
                        protein = value
                    elif '脂質' in label:
                        fat = value
                    elif '糖質' in label:
                        carbs = value
        
        # Формируем результат в формате "368 kcal; 13.6/31.6/8.7"
        if kcal:
            result = f"{kcal} kcal"
            if protein and fat and carbs:
                result += f"; {protein}/{fat}/{carbs}"
            return result
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # На kikkoman.co.jp категория обычно в keywords или можно определить по типу блюда
        # Попробуем извлечь из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Ищем японские категории блюд
            categories = ['和食', '洋食', '中華', 'デザート', 'スープ', 'サラダ', 'メインディッシュ']
            for category in categories:
                if category in keywords:
                    return self.clean_text(category)
        
        # По умолчанию возвращаем "Main Course"
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На данном сайте время обычно не разделено на prep/cook
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем информацию о времени в тексте описания или шагов
        # Паттерны: "10分", "10〜12分", "20〜30分"
        full_text = self.soup.get_text()
        
        # Ищем паттерны времени
        time_pattern = re.search(r'(\d+)(?:〜|～|-)?(\d+)?分', full_text)
        if time_pattern:
            # Берем максимальное время
            time1 = int(time_pattern.group(1))
            time2 = int(time_pattern.group(2)) if time_pattern.group(2) else time1
            return str(max(time1, time2))
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Суммируем prep_time и cook_time если есть
        cook_time = self.extract_cook_time()
        if cook_time:
            return cook_time
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        # Ищем в h4.ttl-lv4-tsushin который содержит "材料（2人分）"
        ingredient_heading = self.soup.find('h4', class_='ttl-lv4-tsushin')
        if ingredient_heading:
            text = ingredient_heading.get_text()
            # Ищем паттерн "X人分"
            match = re.search(r'(\d+)人分', text)
            if match:
                return match.group(1)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # Определяем по наличию слов "簡単" (простой), "レンジ" (микроволновка)
        title = self.extract_dish_name() or ''
        description = self.extract_description() or ''
        
        if '簡単' in title or '簡単' in description or 'レンジ' in title:
            return "Easy"
        
        return "Medium"
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
        # На kikkoman.co.jp обычно нет рейтингов
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем Point секцию
        point_div = self.soup.find('div', class_='point-tsushin')
        if point_div:
            txt_div = point_div.find('div', class_='txt-tsushin')
            if txt_div:
                paragraphs = txt_div.find_all('p')
                if paragraphs:
                    return self.clean_text(paragraphs[0].get_text())
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Извлекаем из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разбиваем по запятым и берем релевантные теги
            tags = [tag.strip() for tag in keywords.split(',')]
            # Фильтруем общие слова
            stopwords = {'キッコーマン', 'ホームクッキング通信', 'ホームクッキング', '醤油', 'しょうゆ'}
            filtered_tags = [tag for tag in tags if tag and tag not in stopwords and len(tag) < 20]
            if filtered_tags:
                return ', '.join(filtered_tags[:5])  # Берем первые 5 тегов
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем изображения рецепта в div.img-tsushin
        img_divs = self.soup.find_all('div', class_='img-tsushin')
        for img_div in img_divs[:3]:  # Берем первые 3
            img = img_div.find('img')
            if img and img.get('src'):
                src = img['src']
                # Преобразуем относительный путь в абсолютный
                if src.startswith('/'):
                    src = f"https://www.kikkoman.co.jp{src}"
                if src not in urls:
                    urls.append(src)
        
        return ', '.join(urls) if urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        step_by_step = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredient": self.extract_ingredients(),
            "step_by_step": step_by_step.lower() if step_by_step else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": notes.lower() if notes else None,
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка рецептов из директории recipes/kikkoman_co_jp"""
    # По умолчанию обрабатываем папку recipes/kikkoman_co_jp
    recipes_dir = "recipes/kikkoman_co_jp"
    if Path(recipes_dir).exists() and Path(recipes_dir).is_dir():
        process_directory(KikkomanExtractor, recipes_dir)
    else:
        print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    main()
