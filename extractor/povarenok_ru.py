"""
Экстрактор данных рецептов для сайта povarenok.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PovarenokRuExtractor(BaseRecipeExtractor):
    """Экстрактор для povarenok.ru"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text()).lower()
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            return self.clean_text(title).lower()
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем блок с описанием - обычно первый <p> после заголовка
        # На povarenok.ru описание находится в начале рецепта
        
        # Пробуем найти через meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем шаблонные фразы
            desc = re.sub(r'Рецепт[ыт]?:', '', desc, flags=re.IGNORECASE)
            desc = re.sub(r'Читать рецепт.*$', '', desc)
            return self.clean_text(desc).lower()
        
        # Ищем первый параграф в описании
        # На povarenok.ru описание обычно идет сразу после заголовка
        content_divs = self.soup.find_all('p')
        for p in content_divs[:3]:  # Проверяем первые 3 параграфа
            text = self.clean_text(p.get_text())
            if len(text) > 50:  # Достаточно длинное описание
                return text.lower()
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов с количеством"""
        ingredients = []
        
        # Способ 1: Ищем li с itemprop="recipeIngredient" (старый формат)
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        # Способ 2: Если не найдены, ищем в div.ingredients-bl (новый формат)
        if not ingredient_items:
            ingredients_div = self.soup.find('div', class_='ingredients-bl')
            if ingredients_div:
                ingredient_items = ingredients_div.find_all('li')
        
        if not ingredient_items:
            return None
        
        for item in ingredient_items:
            # Название ингредиента в span
            # Сначала ищем с itemprop="name" (новый формат)
            name_elem = item.find('span', itemprop='name')
            # Если не найден, ищем первый span в ссылке (старый формат)
            if not name_elem:
                link = item.find('a')
                if link:
                    name_elem = link.find('span')
            
            if not name_elem:
                continue
            
            name = self.clean_text(name_elem.get_text())
            
            # Количество - все span с itemprop="amount"
            amount_spans = item.find_all('span', itemprop='amount')
            amounts = []
            for span in amount_spans:
                amt = self.clean_text(span.get_text())
                if amt:
                    amounts.append(amt)
            
            # Если не найдено через itemprop, ищем последний span (старый формат)
            if not amounts:
                all_spans = item.find_all('span')
                if len(all_spans) > 1:  # Первый - название, последний - количество
                    last_span = all_spans[-1]
                    amt = self.clean_text(last_span.get_text())
                    # Проверяем что это не тот же элемент что и название
                    if amt and last_span != name_elem:
                        amounts.append(amt)
            
            amount = ' '.join(amounts) if amounts else ''
            
            # Также может быть текст между элементами (например, "(отварное)")
            # Собираем текст из всех текстовых узлов li
            item_text = item.get_text(separator=' ', strip=True)
            
            # Извлекаем дополнительный текст в скобках
            extra_parts = []
            for match in re.finditer(r'\(([^)]+)\)', item_text):
                extra = match.group(1).strip()
                # Пропускаем если это название или количество
                if extra and extra not in [name, amount] and len(extra) < 50:
                    extra_parts.append(extra)
            
            if name:
                # Форматируем как "количество название (доп. текст)"
                if amount and extra_parts:
                    extra_text = ', '.join(extra_parts)
                    ingredient = f"{amount} {name} ({extra_text})".lower()
                elif amount:
                    ingredient = f"{amount} {name}".lower()
                else:
                    # Если количества нет, добавляем только название
                    ingredient = name.lower()
                ingredients.append(ingredient)
        
        return ', '.join(ingredients) if ingredients else None
    
    def extract_ingredients_names(self) -> Optional[str]:
        """Извлечение только названий ингредиентов без количества"""
        names = []
        
        # Способ 1: Ищем li с itemprop="recipeIngredient" (старый формат)
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        # Способ 2: Если не найдены, ищем в div.ingredients-bl (новый формат)
        if not ingredient_items:
            ingredients_div = self.soup.find('div', class_='ingredients-bl')
            if ingredients_div:
                ingredient_items = ingredients_div.find_all('li')
        
        if not ingredient_items:
            return None
        
        for item in ingredient_items:
            # Название ингредиента в span
            # Сначала ищем с itemprop="name" (новый формат)
            name_elem = item.find('span', itemprop='name')
            # Если не найден, ищем первый span в ссылке (старый формат)
            if not name_elem:
                link = item.find('a')
                if link:
                    name_elem = link.find('span')
            
            if name_elem:
                name = self.clean_text(name_elem.get_text()).lower()
                if name and name not in names:
                    names.append(name)
        
        return ', '.join(names) if names else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # На povarenok.ru шаги обычно идут пронумерованными параграфами
        # Ищем блоки с описанием шагов
        
        # Вариант 1: Ищем все параграфы с текстом шагов
        # Шаги обычно начинаются после таблицы ингредиентов
        
        step_containers = self.soup.find_all('p')
        step_number = 1
        
        for p in step_containers:
            text = self.clean_text(p.get_text())
            
            # Пропускаем короткие тексты и заголовки
            if len(text) < 20:
                continue
            
            # Пропускаем тексты с ингредиентами
            if 'ингредиент' in text.lower():
                continue
            
            # Проверяем, похоже ли это на шаг приготовления
            # Обычно шаги содержат глаголы действия
            cooking_verbs = ['нарежь', 'наре', 'выложи', 'добавь', 'перемеша', 
                           'охлади', 'натри', 'раздели', 'переложи', 'пропущ',
                           'смеша', 'готовь', 'обжарь', 'вари', 'запек', 'поставь']
            
            has_cooking_verb = any(verb in text.lower() for verb in cooking_verbs)
            
            if has_cooking_verb and len(text) > 30:
                # Добавляем нумерацию если её нет
                if not re.match(r'^\d+\.', text):
                    text = f"{step_number}. {text}"
                    step_number += 1
                steps.append(text.lower())
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 181.9 kcal; 10.8/12.7/5.6"""
        # На povarenok.ru ищем таблицу с пищевой ценностью на 100г блюда
        
        # Ищем все заголовки таблицы с пищевой ценностью
        nae_table = self.soup.find('div', id='nae-value-bl')
        if not nae_table:
            return None
        
        # Ищем все ячейки с классом nae-title
        title_cells = nae_table.find_all('td', class_='nae-title')
        
        for header_cell in title_cells:
            header_text = self.clean_text(header_cell.get_text())
            
            # Ищем ячейку с заголовком "100 г блюда"
            if '100' in header_text and 'блюда' in header_text:
                # Следующая строка после заголовка содержит данные
                header_row = header_cell.find_parent('tr')
                if not header_row:
                    continue
                
                data_row = header_row.find_next_sibling('tr')
                if not data_row:
                    continue
                
                # Извлекаем все td из строки данных
                cells = data_row.find_all('td')
                if len(cells) < 4:
                    continue
                
                # Парсим данные: ккал, белки, жиры, углеводы
                values = []
                for cell in cells:
                    strong = cell.find('strong')
                    if strong:
                        text = self.clean_text(strong.get_text())
                        # Убираем единицы измерения
                        text = text.replace('ккал', '').replace('г', '').strip()
                        values.append(text)
                
                if len(values) >= 4:
                    # Формат: "181.9 kcal; 10.8/12.7/5.6"
                    kcal = values[0]
                    protein = values[1]
                    fat = values[2]
                    carbs = values[3]
                    
                    return f"{kcal} kcal; {protein}/{fat}/{carbs}".lower()
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках или тегах
        # На povarenok.ru есть раздел "Рецепты:"
        
        # Ищем в blog_code секции
        blog_code = self.soup.find('div', id='blog_code')
        if blog_code:
            text = blog_code.get_text()
            # Ищем строку "Рецепты: ..."
            match = re.search(r'Рецепты:\s*([^\n]+)', text)
            if match:
                category = match.group(1).strip()
                # Убираем стрелки и берем последнюю категорию
                category = category.split('->')[-1].strip()
                return self.clean_text(category).lower()
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На povarenok.ru время обычно не разделено на prep/cook
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Можем попробовать найти время в тексте
        # Обычно указывается в формате "1 час 30 минут" или подобном
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем время в тексте
        text = self.soup.get_text()
        
        # Паттерны для поиска времени
        time_patterns = [
            r'(\d+)\s*час[а|ов]?\s*(\d+)?\s*минут',
            r'(\d+)\s*минут',
            r'(\d+)\s*час[а|ов]?'
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                hours = int(match.group(1)) if match.group(1) else 0
                minutes = int(match.group(2)) if len(match.groups()) > 1 and match.group(2) else 0
                
                if 'час' in pattern:
                    total_minutes = hours * 60 + minutes
                else:
                    total_minutes = hours  # Это минуты
                
                return str(total_minutes) if total_minutes > 0 else None
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        # Ищем в тексте или в специальных полях
        # На povarenok.ru порции могут быть указаны в таблице
        
        text = self.soup.get_text()
        
        # Паттерны для поиска порций
        servings_patterns = [
            r'(\d+)\s*порци[йяи]',
            r'на\s*(\d+)\s*человек',
            r'(\d+)\s*персон'
        ]
        
        for pattern in servings_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На povarenok.ru сложность обычно не указывается
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем дополнительные советы или примечания
        # Обычно идут в конце рецепта
        
        # Можем поискать параграфы с ключевыми словами
        note_keywords = ['совет', 'примечание', 'важно', 'можно', 'лучше']
        
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = self.clean_text(p.get_text())
            if any(keyword in text.lower() for keyword in note_keywords):
                if len(text) > 20 and len(text) < 500:
                    return text.lower()
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (включая теги и вкусы)"""
        tags = []
        
        # На povarenok.ru теги указаны в blog_code секции
        blog_code = self.soup.find('div', id='blog_code')
        if blog_code:
            text = blog_code.get_text()
            
            # Ищем строку "Тэги: ..."
            tags_match = re.search(r'Тэги:\s*([^\n]+)', text, re.IGNORECASE)
            if tags_match:
                tags_str = tags_match.group(1).strip()
                # Разделяем по запятой и точке
                tag_items = re.split(r'[,.]', tags_str)
                for tag in tag_items:
                    tag = self.clean_text(tag).lower()
                    if tag and len(tag) > 2:
                        tags.append(tag)
            
            # Ищем вкусы если есть отдельная строка
            taste_match = re.search(r'Вкус[ы]?:\s*([^\n]+)', text, re.IGNORECASE)
            if taste_match:
                tastes_str = taste_match.group(1).strip()
                taste_items = re.split(r'[,.]', tastes_str)
                for taste in taste_items:
                    taste = self.clean_text(taste).lower()
                    if taste and len(taste) > 2 and taste not in tags:
                        tags.append(taste)
        
        # Также можем поискать keywords в meta тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content'].split(',')
            for kw in keywords:
                kw = self.clean_text(kw).lower()
                if kw and len(kw) > 2 and kw not in tags:
                    tags.append(kw)
        
        return ', '.join(tags) if tags else None
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
        # На povarenok.ru есть рейтинговая система
        # Ищем элементы с рейтингом
        
        # Можем поискать в meta данных или в специальных div
        rating_elem = self.soup.find(class_=re.compile(r'rating', re.I))
        if rating_elem:
            text = rating_elem.get_text()
            # Ищем число (рейтинг обычно от 1 до 5)
            match = re.search(r'(\d+(?:\.\d+)?)', text)
            if match:
                try:
                    rating = float(match.group(1))
                    if 0 <= rating <= 5:
                        return rating
                except ValueError:
                    pass
        
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
        ingredients_names = self.extract_ingredients_names()
        step_by_step = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "ingredients_names": ingredients_names,
            "step_by_step": step_by_step,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": notes,
            "tags": tags
        }


def main():
    import os
    # По умолчанию обрабатываем папку recipes/povarenok_ru
    recipes_dir = os.path.join("recipes", "povarenok_ru")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(PovarenokRuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python povarenok_ru.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
