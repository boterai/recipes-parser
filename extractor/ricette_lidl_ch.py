"""
Экстрактор данных рецептов для сайта ricette.lidl.ch
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RicetteLidlChExtractor(BaseRecipeExtractor):
    """Экстрактор для ricette.lidl.ch"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из title тега
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
            # Фильтруем если это просто "Lidl Recipes"
            if desc and desc.lower() != 'lidl recipes':
                return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc and desc.lower() != 'lidl recipes':
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем уникальные элементы ингредиентов через data-testid
        ingredient_labels = self.soup.find_all('label', attrs={'data-testid': re.compile(r'ingredient-.*-label')})
        
        if ingredient_labels:
            # Используем уникальные label элементы
            for label in ingredient_labels:
                # Извлекаем все span элементы в label
                all_spans = label.find_all('span', recursive=True)
                
                # Структура:
                # Span 0 & 1: Amount (с классом font-headline_6-prominent)
                # Span 2: Unit (если есть, с классом font-headline_6-prominent) ИЛИ Name
                # Span 3: Name (с классом font-headline_6-base)
                # Span 4: Extra info (опционально, с классом font-headline_6-base) - может содержать доп. количество!
                
                amount = None
                units = None
                name = None
                
                # Найдем span с классом font-headline_6-base (это название и доп. инфо)
                base_spans = [s for s in all_spans if s.get('class') and 
                             any('font-headline_6-base' in c for c in s.get('class', []))]
                
                if base_spans:
                    # Первый font-headline_6-base span - это название
                    name = self.clean_text(base_spans[0].get_text())
                
                # Найдем span с количеством (с data-testid="quantity-from")
                amount_span = label.find('span', attrs={'data-testid': 'quantity-from'})
                if amount_span:
                    amount_text = self.clean_text(amount_span.get_text())
                    # Проверяем, что это число
                    try:
                        float(amount_text.replace(',', '.'))
                        amount = amount_text
                    except (ValueError, AttributeError):
                        pass
                
                # Найдем span с единицей измерения (с классом font-headline_6-prominent, но не количество)
                unit_spans = [s for s in all_spans if s.get('class') and 
                             any('font-headline_6-prominent' in c for c in s.get('class', []))]
                
                # Фильтруем unit_spans: пропускаем количество и ищем единицу
                for unit_span in unit_spans:
                    text = self.clean_text(unit_span.get_text())
                    # Пропускаем, если это количество
                    if amount and text == str(amount):
                        continue
                    # Проверяем, является ли это единицей измерения
                    common_units = ['g', 'kg', 'ml', 'l', 'dl', 'cl', 'pezzo', 'pezzi', 
                                   'cucchiai', 'cucchiaio', 'cucchiaini', 'cucchiaino', 
                                   'tazze', 'tazza', 'pizzico']
                    if text.lower() in common_units or text in ['g', 'kg', 'ml', 'l', 'dl', 'cl']:
                        units = text
                        break
                
                # Если units НЕ найдены (None), проверяем extra_info
                # Например для "cipolla" у нас есть "1" но нет единицы, проверяем доп. инфо
                # Для "radici di zenzero" у нас "1 pezzo" но в доп. инфо "ca. 20 g" - используем доп. инфо
                if len(base_spans) > 1:
                    extra_info = self.clean_text(base_spans[1].get_text())
                    # Попробуем извлечь количество и единицу из extra_info
                    # Паттерн: "ca. 20 g", "ca. 650 g ciascuna"
                    extra_match = re.search(r'(?:ca\.\s*)?(\d+)\s*([a-zA-Z]+)', extra_info)
                    if extra_match:
                        extra_amount, extra_unit = extra_match.groups()
                        
                        # Используем extra info ТОЛЬКО если:
                        # 1. У нас нет единицы измерения (units is None) - для ингредиентов без единиц типа "cipolla"
                        # 2. ИЛИ единица измерения более конкретная (g/ml вместо pezzo)
                        if units is None:
                            # Нет основной единицы, не используем extra (это может быть "ciascuna")
                            pass
                        elif units.lower() in ['pezzo', 'pezzi'] and extra_unit.lower() in ['g', 'kg', 'ml', 'l']:
                            # У нас "pezzo" но в extra есть конкретная единица (g/ml), используем extra
                            amount = extra_amount
                            units = extra_unit
                
                if name:
                    ingredient = {
                        "name": name,
                        "amount": int(amount) if amount and amount.isdigit() else amount,
                        "units": units
                    }
                    ingredients.append(ingredient)
        else:
            # Fallback: используем старый метод, если не найдены label элементы
            # Ищем все элементы span с классом font-headline_6-base (названия ингредиентов)
            ingredient_name_spans = self.soup.find_all('span', class_=re.compile(r'font-headline_6-base'))
            
            seen_ingredients = set()
            
            for name_span in ingredient_name_spans:
                name = self.clean_text(name_span.get_text())
                
                if not name or name.lower() in seen_ingredients:
                    continue
                
                # Получаем родительский div с flex-row
                parent_div = name_span.parent
                if not parent_div:
                    continue
                
                row_div = parent_div.parent if parent_div.parent else parent_div
                
                # Извлекаем все span элементы
                all_spans = row_div.find_all('span', recursive=True)
                
                amount = None
                units = None
                
                # Ищем количество (первый span с числом)
                for span in all_spans:
                    text = self.clean_text(span.get_text())
                    try:
                        float(text.replace(',', '.'))
                        amount = text
                        break
                    except (ValueError, AttributeError):
                        pass
                
                # Ищем единицу измерения
                for span in all_spans:
                    text = self.clean_text(span.get_text())
                    if text == name or (amount and text == amount):
                        continue
                    common_units = ['g', 'kg', 'ml', 'l', 'pezzo', 'pezzi', 'cucchiai', 'cucchiaio']
                    if text.lower() in common_units:
                        units = text
                        break
                
                ingredient = {
                    "name": name,
                    "amount": int(amount) if amount and amount.isdigit() else amount,
                    "units": units
                }
                
                ingredients.append(ingredient)
                seen_ingredients.add(name.lower())
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Ищем ordered list с классом list-decimal (инструкции)
        ol = self.soup.find('ol', class_=re.compile(r'list-decimal'))
        
        if ol:
            # Вариант 1: Инструкции в параграфах <p>
            steps = ol.find_all('p', class_=re.compile(r'font-body'))
            
            if steps:
                # Объединяем все шаги в одну строку
                instructions_text = ' '.join([self.clean_text(step.get_text()) for step in steps])
                return instructions_text if instructions_text else None
            
            # Вариант 2: Инструкции в элементах списка <li>
            lis = ol.find_all('li', recursive=False)
            
            if lis:
                # Извлекаем текст из каждого <li>
                instructions_text = ' '.join([self.clean_text(li.get_text()) for li in lis])
                return instructions_text if instructions_text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем в meta keywords - там могут быть категории
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords.get('content')
            # Категории обычно в конце списка ключевых слов
            # Примеры: "Piatto principale", "Antipasto", "Vegetariano"
            keyword_list = [k.strip() for k in keywords.split(',')]
            
            # Ищем известные категории
            categories = []
            known_categories = [
                'Piatto principale', 'Antipasto', 'Dessert', 'Dolci', 
                'Zuppe', 'Insalate', 'Vegetariano', 'Vegano',
                'Frutta e verdura', 'Carne', 'Pesce'
            ]
            
            for keyword in keyword_list:
                if keyword in known_categories:
                    categories.append(keyword)
            
            if categories:
                return ', '.join(categories)
        
        return None
    
    def extract_time_field(self, field_name: str) -> Optional[str]:
        """Извлечение времени (prep_time, cook_time, total_time)"""
        # Ищем в meta keywords время
        # Обычно время указано в формате "15 min", "1 h 25 min"
        
        # Для ricette.lidl.ch время может быть в разных местах
        # Попробуем найти текст с паттерном времени
        
        # Ищем все текстовые элементы с паттерном времени
        time_pattern = re.compile(r'(\d+\s*(?:h|min|ore|minuti)(?:\s*\d+\s*(?:min|minuti))?)', re.I)
        
        # Ищем элементы, которые могут содержать время
        # Обычно это элементы с определенными классами или рядом с иконками
        
        # Попробуем найти в body
        body_text = self.soup.get_text(separator=' ')
        
        # Ищем паттерны времени
        time_matches = time_pattern.findall(body_text)
        
        if time_matches:
            # Возвращаем первое найденное время
            # Это упрощенный подход, в реальности нужно различать prep/cook/total
            return self.clean_text(time_matches[0])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем элемент с data-testid="recipe-info-badge-preparation"
        prep_badge = self.soup.find(attrs={'data-testid': 'recipe-info-badge-preparation'})
        if prep_badge:
            # Извлекаем текст и ищем паттерн времени
            text = prep_badge.get_text(strip=True)
            # Паттерн: "PreparazionePreparazione15 min"
            time_match = re.search(r'(\d+\s*(?:h|min|ore|minuti)(?:\s*\d+\s*(?:min|minuti))?)', text, re.I)
            if time_match:
                return self.clean_text(time_match.group(1))
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем элемент с data-testid="recipe-info-badge-cooking"
        cook_badge = self.soup.find(attrs={'data-testid': 'recipe-info-badge-cooking'})
        if cook_badge:
            # Извлекаем текст и ищем паттерн времени
            text = cook_badge.get_text(strip=True)
            # Паттерн: "CotturaCottura15 min"
            time_match = re.search(r'(\d+\s*(?:h|min|ore|minuti)(?:\s*\d+\s*(?:min|minuti))?)', text, re.I)
            if time_match:
                return self.clean_text(time_match.group(1))
        
        # Fallback: используем общий метод
        return self.extract_time_field('cook_time')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем элемент с data-testid="recipe-info-badge-total" (если есть)
        total_badge = self.soup.find(attrs={'data-testid': 'recipe-info-badge-total'})
        if total_badge:
            text = total_badge.get_text(strip=True)
            time_match = re.search(r'(\d+\s*(?:h|min|ore|minuti)(?:\s*\d+\s*(?:min|minuti))?)', text, re.I)
            if time_match:
                return self.clean_text(time_match.group(1))
        
        # Fallback: используем общий метод
        return self.extract_time_field('total_time')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с примечаниями
        # Примечания могут быть внутри ordered list после основных инструкций
        # или после ordered list
        
        ol = self.soup.find('ol', class_=re.compile(r'list-decimal'))
        
        if ol:
            notes_paragraphs = []
            
            # Ищем все параграфы внутри ol
            all_ps = ol.find_all('p', class_=re.compile(r'font-body'))
            
            # Примечания обычно начинаются с определенных ключевых слов
            # или идут после короткого параграфа с заголовком типа "Consiglio:"
            note_keywords = ['naturalmente', 'consiglio', 'nota', 'suggerimento', 'importante']
            
            is_note_section = False
            for i, p in enumerate(all_ps):
                text = self.clean_text(p.get_text())
                
                # Проверяем, является ли это заголовком примечания
                if text and len(text) < 20 and any(keyword in text.lower() for keyword in note_keywords):
                    is_note_section = True
                    continue  # Пропускаем сам заголовок
                
                # Если мы в секции примечаний, добавляем текст
                if is_note_section and text and len(text) > 30:
                    notes_paragraphs.append(text)
                
                # Также проверяем, начинается ли параграф с ключевого слова
                if text and any(text.lower().startswith(keyword) for keyword in note_keywords):
                    if text not in notes_paragraphs:
                        notes_paragraphs.append(text)
            
            # Также ищем параграфы после ordered list
            if not notes_paragraphs:
                current = ol.find_next('p', class_=re.compile(r'font-body'))
                count = 0
                
                # Получаем тексты инструкций для исключения
                instruction_texts = [self.clean_text(p.get_text()) for p in all_ps]
                
                while current and count < 5:
                    text = self.clean_text(current.get_text())
                    
                    # Пропускаем инструкции
                    if text in instruction_texts:
                        current = current.find_next('p', class_=re.compile(r'font-body'))
                        count += 1
                        continue
                    
                    # Проверяем длину и добавляем
                    if text and len(text) > 30:
                        # Проверяем, не является ли это частью секции питания
                        parent_text = current.parent.get_text() if current.parent else ''
                        if 'calorie' not in parent_text.lower() and 'nutrition' not in parent_text.lower():
                            notes_paragraphs.append(text)
                    
                    current = current.find_next('p', class_=re.compile(r'font-body'))
                    count += 1
                    
                    if len(notes_paragraphs) >= 2:
                        break
            
            if notes_paragraphs:
                return ' '.join(notes_paragraphs)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега keywords"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords.get('content')
            # Возвращаем как есть, разделенные запятыми
            # Можем отфильтровать некоторые системные категории
            keyword_list = [k.strip() for k in keywords.split(',')]
            
            # Фильтруем системные категории (оставляем их, но можем убрать совсем базовые)
            # В данном случае оставляем все
            
            return keywords
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем изображения в body
        # Ищем img теги с src начинающимся с https://cdn.recipes.lidl
        images = self.soup.find_all('img', src=re.compile(r'https://cdn\.recipes\.lidl'))
        for img in images:
            src = img.get('src')
            if src and src not in urls:
                urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем первые 3 URL через запятую
        if unique_urls:
            return ','.join(unique_urls[:3])
        
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
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Путь к директории с preprocessed HTML
    recipes_dir = os.path.join("preprocessed", "ricette_lidl_ch")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RicetteLidlChExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ricette_lidl_ch.py")


if __name__ == "__main__":
    main()
