"""
Экстрактор данных рецептов для сайта blog.giallozafferano.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BlogGiallozafferanoExtractor(BaseRecipeExtractor):
    """Экстрактор для blog.giallozafferano.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом entry-title
        title_h1 = self.soup.find('h1', class_='entry-title')
        if title_h1:
            title_text = self.clean_text(title_h1.get_text())
            # Убираем префиксы типа "Come cucinare"
            title_text = re.sub(r'^Come cucinare\s+', '', title_text, flags=re.IGNORECASE)
            return title_text
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description (обычно это короткое описание)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc_text = self.clean_text(meta_desc['content'])
            # Проверяем, не слишком ли длинное
            if desc_text and len(desc_text) < 300:
                return desc_text
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc_text = self.clean_text(og_desc['content'])
            if desc_text and len(desc_text) < 300:
                return desc_text
        
        # Ищем в блоке introduction
        intro = self.soup.find('div', class_='wp-block-altervista-introduction')
        if intro:
            # Берем первое предложение или первый параграф
            intro_text = self.clean_text(intro.get_text())
            # Берем первое предложение
            sentences = intro_text.split('.')
            if sentences:
                first_sentence = sentences[0].strip() + '.'
                if len(first_sentence) > 20:
                    return first_sentence
        
        # Возвращаем meta description даже если длинное
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Пробуем новый стиль (wp-block-altervista-ingredients)
        ingredients_block = self.soup.find('div', class_='wp-block-altervista-ingredients')
        if ingredients_block:
            # Извлекаем отдельные ингредиенты (новый стиль)
            ing_items = ingredients_block.find_all('div', class_='wp-block-altervista-ingredient')
            
            for item in ing_items:
                # Ищем компоненты ингредиента
                name_elem = item.find(class_='ingredient-name')
                
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                    amount = None
                    unit = None
                    
                    # Ищем qty-wrapper который содержит amount и unit
                    qty_wrapper = item.find(class_='ingredient-qty-wrapper')
                    if qty_wrapper:
                        # Ищем number (может быть с классом ingredient-number или ingredient-qty)
                        number_elem = qty_wrapper.find(class_=re.compile(r'ingredient-(number|qty)'))
                        unit_elem = qty_wrapper.find(class_='ingredient-unit')
                        
                        if number_elem:
                            amount_text = self.clean_text(number_elem.get_text())
                            # Преобразуем в число если возможно
                            try:
                                amount = int(amount_text)
                            except ValueError:
                                try:
                                    amount = float(amount_text)
                                except ValueError:
                                    amount = amount_text
                        
                        if unit_elem:
                            unit = self.clean_text(unit_elem.get_text())
                    
                    # Если amount не найден, но unit есть - возможно это "q.b." или подобное
                    if not amount and unit:
                        amount = unit
                        unit = None
                    
                    # Формируем структуру согласно эталону (units, а не unit!)
                    ingredient = {
                        "name": name,
                        "units": unit,
                        "amount": amount
                    }
                    ingredients.append(ingredient)
        else:
            # Пробуем старый стиль (recipe-ingredients-content)
            ingredients_content = self.soup.find('div', class_='recipe-ingredients-content')
            if ingredients_content:
                ing_items = ingredients_content.find_all('div', class_='recipe-ingredient-item')
                
                for item in ing_items:
                    # Старый стиль: qty и name отдельно
                    name_elem = item.find(class_='recipe-ingredient-name')
                    qty_elem = item.find(class_='recipe-ingredient-qty')
                    
                    if name_elem:
                        name = self.clean_text(name_elem.get_text())
                        amount = None
                        unit = None
                        
                        if qty_elem:
                            # Внутри qty может быть number и unit
                            number_elem = qty_elem.find(class_='recipe-ingredient-number')
                            unit_elem = qty_elem.find(class_='recipe-ingredient-unit')
                            
                            if number_elem:
                                amount_text = self.clean_text(number_elem.get_text())
                                # Преобразуем в число если возможно
                                try:
                                    amount = int(amount_text)
                                except ValueError:
                                    try:
                                        amount = float(amount_text)
                                    except ValueError:
                                        amount = amount_text
                            
                            if unit_elem:
                                unit = self.clean_text(unit_elem.get_text())
                        
                        ingredient = {
                            "name": name,
                            "units": unit,
                            "amount": amount
                        }
                        ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Пробуем новый стиль (wp-block-altervista-steps)
        steps_block = self.soup.find('div', class_='wp-block-altervista-steps')
        if steps_block:
            # Извлекаем отдельные шаги
            step_items = steps_block.find_all('div', class_='wp-block-altervista-step')
            
            for step_item in step_items:
                # Ищем параграфы с текстом шага
                paragraphs_div = step_item.find('div', class_='wp-block-altervista-paragraphs')
                if paragraphs_div:
                    step_text = paragraphs_div.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        else:
            # Пробуем старый стиль (recipe-steps)
            steps_div = self.soup.find('div', class_='recipe-steps')
            if steps_div:
                steps_ol = steps_div.find('ol')
                if steps_ol:
                    step_items = steps_ol.find_all('li', recursive=False)
                    for step_item in step_items:
                        # Собираем текст из всех параграфов в шаге
                        paragraphs = step_item.find_all('p')
                        if paragraphs:
                            step_texts = []
                            for p in paragraphs:
                                p_text = self.clean_text(p.get_text())
                                if p_text:
                                    step_texts.append(p_text)
                            if step_texts:
                                steps.append(' '.join(step_texts))
                        else:
                            # Если нет параграфов, берем весь текст li
                            step_text = self.clean_text(step_item.get_text())
                            if step_text:
                                steps.append(step_text)
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Для данного сайта информация о питательности не найдена в HTML
        # Возвращаем None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных поста
        category_div = self.soup.find('div', class_='post-category')
        if category_div:
            # Берем вторую категорию, если есть (первая часто слишком специфична)
            links = category_div.find_all('a')
            if len(links) >= 2:
                # Проверяем, какая категория больше подходит
                # Предпочитаем Main Course, Antipasto, Dessert и т.п.
                for link in links:
                    cat_text = self.clean_text(link.get_text())
                    # Ищем известные категории блюд
                    if cat_text in ['Antipasto', 'Primi piatti', 'Secondi piatti', 'Contorni', 'Dolci', 'Main Course', 'Dessert', 'Appetizer']:
                        return cat_text
                # Если не нашли, берем первую
                return self.clean_text(links[0].get_text())
            elif links:
                return self.clean_text(links[0].get_text())
        
        # Альтернативно - из мета-тега
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('preptime', 'cooktime', 'totaltime')
        """
        # Ищем в блоке recipe-info
        recipe_info = self.soup.find('ul', class_='recipe-info')
        if not recipe_info:
            return None
        
        # Ищем элемент li с нужным классом
        time_item = recipe_info.find('li', class_=time_type)
        if time_item:
            value_elem = time_item.find(class_='recipe-value')
            if value_elem:
                time_text = self.clean_text(value_elem.get_text())
                # Нормализуем формат: "5 Minuti" -> "5 minutes"
                time_text = re.sub(r'\bMinuti?\b', 'minutes', time_text, flags=re.IGNORECASE)
                time_text = re.sub(r'\bOre?\b', 'hours', time_text, flags=re.IGNORECASE)
                return time_text
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('preptime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cooktime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Попробуем найти totaltime
        total = self.extract_time('totaltime')
        if total:
            return total
        
        # Если не нашли, попробуем найти другие варианты
        recipe_info = self.soup.find('ul', class_='recipe-info')
        if recipe_info:
            # Ищем все элементы времени
            time_items = recipe_info.find_all('li')
            for item in time_items:
                label = item.find(class_='recipe-label')
                value = item.find(class_='recipe-value')
                if label and value:
                    label_text = label.get_text().strip().lower()
                    if 'totale' in label_text or 'total' in label_text:
                        return self.clean_text(value.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем блок notes
        notes_div = self.soup.find('div', class_='wp-block-altervista-notes')
        if notes_div:
            text = notes_div.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в блоке post-tags
        tags_div = self.soup.find('div', class_='post-tags')
        if tags_div:
            tag_links = tags_div.find_all('a')
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text:
                    tags.append(tag_text)
        
        # Возвращаем как строку через запятую
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в блоке recipe-cover или wp-block-altervista-cover
        cover = self.soup.find('div', class_='wp-block-altervista-cover')
        if not cover:
            cover = self.soup.find('div', class_='recipe-cover')
        
        if cover:
            images = cover.find_all('img')
            for img in images:
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
        
        # 3. Ищем изображения в шагах
        steps_block = self.soup.find('div', class_='wp-block-altervista-steps')
        if steps_block:
            step_images = steps_block.find_all('img')
            for img in step_images[:3]:  # Берем первые 3
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
        
        # Убираем дубликаты и возвращаем через запятую
        if urls:
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_urls = []
            for url in urls:
                if url not in seen:
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
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": self.extract_nutrition_info(),
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
    # По умолчанию обрабатываем папку preprocessed/blog_giallozafferano_it
    recipes_dir = os.path.join("preprocessed", "blog_giallozafferano_it")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BlogGiallozafferanoExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python blog_giallozafferano_it.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
