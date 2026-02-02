"""
Экстрактор данных рецептов для сайта tillmiddag.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TillmiddagExtractor(BaseRecipeExtractor):
    """Экстрактор для tillmiddag.se"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Tillmiddag"
            title = re.sub(r'\s+[-–]\s+Tillmiddag.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в entry-summary (описание перед рецептом)
        entry_summary = self.soup.find('div', class_='entry-summary')
        if entry_summary:
            # Берем первый параграф
            p = entry_summary.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном виде"""
        ingredients = []
        
        # Ищем список ингредиентов
        ingredients_list = self.soup.find('ul', class_='ingredients-list')
        
        if ingredients_list:
            items = ingredients_list.find_all('li')
            
            for item in items:
                # Извлекаем количество, единицу и название
                qty_span = item.find('span', class_='ing-qty')
                unit_span = item.find('span', class_='ing-unit')
                rest_span = item.find('span', class_='ing-rest')
                
                amount = None
                unit = None
                name = None
                
                if qty_span:
                    amount_text = self.clean_text(qty_span.get_text())
                    # Обработка дробей и чисел
                    amount_text = amount_text.replace(',', '.')
                    # Заменяем Unicode дроби
                    fraction_map = {
                        '½': '0.5', '¼': '0.25', '¾': '0.75',
                        '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
                        '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
                    }
                    for fraction, decimal in fraction_map.items():
                        amount_text = amount_text.replace(fraction, decimal)
                    
                    # Обработка дробей типа "1/2"
                    if '/' in amount_text:
                        try:
                            parts = amount_text.split()
                            total = 0
                            for part in parts:
                                if '/' in part:
                                    num, denom = part.split('/')
                                    total += float(num) / float(denom)
                                else:
                                    total += float(part)
                            amount = total
                        except:
                            amount = amount_text
                    else:
                        try:
                            amount = float(amount_text) if '.' in amount_text else int(float(amount_text))
                        except:
                            amount = amount_text
                
                if unit_span:
                    unit = self.clean_text(unit_span.get_text())
                
                if rest_span:
                    name_text = self.clean_text(rest_span.get_text())
                    # Убираем скобки с дополнительной информацией
                    name_text = re.sub(r'\([^)]*\)', '', name_text)
                    # Убираем фразы "valfritt", "efter smak"
                    name_text = re.sub(r'\b(valfritt|efter smak|till servering)\b', '', name_text, flags=re.IGNORECASE)
                    name_text = re.sub(r'[,;]+$', '', name_text)
                    name_text = re.sub(r'\s+', ' ', name_text).strip()
                    name = name_text
                
                if name:
                    ingredient_dict = {
                        "name": name,
                        "units": unit,
                        "amount": amount
                    }
                    ingredients.append(ingredient_dict)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Ищем упорядоченный список инструкций
        instructions_section = self.soup.find('section')
        if instructions_section:
            h2 = instructions_section.find('h2')
            if h2 and 'instruktion' in h2.get_text().lower():
                ol = instructions_section.find('ol')
                if ol:
                    items = ol.find_all('li')
                    for item in items:
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            steps.append(step_text)
        
        # Если не нашли через section, ищем напрямую ol после заголовка
        if not steps:
            for h2 in self.soup.find_all('h2'):
                if 'instruktion' in h2.get_text().lower():
                    ol = h2.find_next('ol')
                    if ol:
                        items = ol.find_all('li')
                        for item in items:
                            step_text = self.clean_text(item.get_text())
                            if step_text:
                                steps.append(step_text)
                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория находится в классах article элемента
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            # Ищем классы tillmiddag_course
            course_classes = [c for c in classes if c.startswith('tillmiddag_course-')]
            if course_classes:
                # Берем первый, убираем префикс и заменяем дефисы на пробелы
                category = course_classes[0].replace('tillmiddag_course-', '').replace('-', ' ')
                return self.clean_text(category.title())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из fact-box
        
        Args:
            time_type: 'prep' для Förberedelser, 'total' для Totalt
        """
        fact_box = self.soup.find('section', class_='fact-box')
        if not fact_box:
            return None
        
        # Маппинг типов времени на шведские термины
        time_labels = {
            'prep': 'Förberedelser',
            'total': 'Totalt',
            'cook': 'Tillagning'  # На случай если есть
        }
        
        label = time_labels.get(time_type)
        if not label:
            return None
        
        # Ищем dt с нужным текстом
        dts = fact_box.find_all('dt')
        for dt in dts:
            if label.lower() in dt.get_text().lower():
                # Находим следующий dd
                dd = dt.find_next('dd')
                if dd:
                    return self.clean_text(dd.get_text())
        
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
        """Извлечение заметок и советов из tip-box"""
        notes = []
        
        # Ищем все tip-box details
        tip_boxes = self.soup.find_all('details', class_='tip-box')
        
        for tip_box in tip_boxes:
            # Извлекаем заголовок из summary
            summary = tip_box.find('summary', class_='tip-summary')
            # Извлекаем содержимое из tip-content
            content = tip_box.find('div', class_='tip-content')
            
            if summary and content:
                title = self.clean_text(summary.get_text())
                text = self.clean_text(content.get_text())
                # Комбинируем заголовок и текст
                note = f"{title}: {text}"
                notes.append(note)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из классов article"""
        tags = []
        
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            
            # Собираем все taxonomy классы
            # tillmiddag_course - типы блюд
            course_tags = [c.replace('tillmiddag_course-', '').replace('-', ' ').title() 
                          for c in classes if c.startswith('tillmiddag_course-')]
            
            # tillmiddag_cuisine - кухни
            cuisine_tags = [c.replace('tillmiddag_cuisine-', '').replace('-', ' ').title() 
                           for c in classes if c.startswith('tillmiddag_cuisine-')]
            
            # tillmiddag_theme - темы
            theme_tags = [c.replace('tillmiddag_theme-', '').replace('-', ' ').title() 
                         for c in classes if c.startswith('tillmiddag_theme-')]
            
            # tillmiddag_difficulty - сложность
            difficulty_tags = [c.replace('tillmiddag_difficulty-', '').replace('-', ' ').title() 
                              for c in classes if c.startswith('tillmiddag_difficulty-')]
            
            # Объединяем все теги
            tags.extend(cuisine_tags)
            tags.extend(course_tags)
            tags.extend(theme_tags)
            tags.extend(difficulty_tags)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в wp-post-image (главное изображение рецепта)
        post_image = self.soup.find('img', class_='wp-post-image')
        if post_image and post_image.get('src'):
            urls.append(post_image['src'])
        
        # 3. Ищем другие изображения в recipe контенте
        article = self.soup.find('article', class_='tillmiddag_recipe')
        if article:
            images = article.find_all('img')
            for img in images:
                if img.get('src') and 'uploads' in img['src']:
                    urls.append(img['src'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
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
    """Обработка примеров из preprocessed/tillmiddag_se"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "tillmiddag_se")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TillmiddagExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Убедитесь, что вы запускаете скрипт из корня репозитория")


if __name__ == "__main__":
    main()
