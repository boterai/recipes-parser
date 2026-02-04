"""
Экстрактор данных рецептов для сайта bitemybun.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BitemybunExtractor(BaseRecipeExtractor):
    """Экстрактор для bitemybun.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            if 'name' in item:
                                name = self.clean_text(item['name'])
                                if name:
                                    return name
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в WPRM recipe name
        recipe_name = self.soup.find(class_='wprm-recipe-name')
        if recipe_name:
            name = self.clean_text(recipe_name.get_text())
            if name:
                return name
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            if 'description' in item:
                                desc = self.clean_text(item['description'])
                                if desc:
                                    return desc
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в WPRM recipe summary
        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            desc = self.clean_text(summary.get_text())
            if desc:
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем список ингредиентов WPRM
        ingredients_list = self.soup.find('ul', class_='wprm-recipe-ingredients')
        
        if ingredients_list:
            items = ingredients_list.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in items:
                # Извлекаем структурированные данные
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')
                
                # Получаем текст или None
                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                name = self.clean_text(name_elem.get_text()) if name_elem else None
                
                # Нормализуем пустые строки в None
                if amount and amount.lower() == 'none':
                    amount = None
                if unit and unit.lower() == 'none':
                    unit = None
                
                # Convert amount to number if possible
                if amount:
                    # Replace fractions
                    amount = amount.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                    amount = amount.replace('⅓', '0.33').replace('⅔', '0.67')
                    try:
                        # Try to convert to number
                        if '.' in amount:
                            amount = float(amount)
                        else:
                            amount = int(amount)
                    except ValueError:
                        # Keep as string if conversion fails
                        pass
                
                if name:
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем список инструкций WPRM
        instructions_list = self.soup.find('ul', class_='wprm-recipe-instructions')
        
        if instructions_list:
            items = instructions_list.find_all('li', class_='wprm-recipe-instruction')
            
            for item in items:
                text_elem = item.find(class_='wprm-recipe-instruction-text')
                if text_elem:
                    text = self.clean_text(text_elem.get_text())
                    if text:
                        instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в WPRM recipe course
        course = self.soup.find(class_='wprm-recipe-course')
        if course:
            category = self.clean_text(course.get_text())
            if category:
                return category
        
        # Альтернативно - из метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в WPRM
        prep_time = self.soup.find(class_='wprm-recipe-prep_time-minutes')
        if prep_time:
            time_text = self.clean_text(prep_time.get_text())
            if time_text:
                # Убираем лишние слова типа "zapisnik"
                time_text = re.sub(r'zapisnik|minutes?', '', time_text, flags=re.I).strip()
                return f"{time_text} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в WPRM
        cook_time = self.soup.find(class_='wprm-recipe-cook_time-minutes')
        if cook_time:
            time_text = self.clean_text(cook_time.get_text())
            if time_text:
                # Убираем лишние слова
                time_text = re.sub(r'zapisnik|minutes?', '', time_text, flags=re.I).strip()
                return f"{time_text} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в WPRM
        total_time = self.soup.find(class_='wprm-recipe-total_time-minutes')
        if total_time:
            time_text = self.clean_text(total_time.get_text())
            if time_text:
                # Убираем лишние слова
                time_text = re.sub(r'zapisnik|minutes?', '', time_text, flags=re.I).strip()
                return f"{time_text} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            # Некоторые рецепты могут иметь notes в JSON-LD
                            if 'recipeNotes' in item:
                                notes_text = self.clean_text(item['recipeNotes'])
                                if notes_text:
                                    return notes_text
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в WPRM recipe notes
        recipe_div = self.soup.find('div', class_='wprm-recipe')
        if recipe_div:
            notes = recipe_div.find(class_='wprm-recipe-notes')
            if notes:
                notes_text = self.clean_text(notes.get_text())
                # Убираем заголовок "Notes:" если есть
                notes_text = re.sub(r'^notes?\s*:?\s*', '', notes_text, flags=re.I).strip()
                if notes_text and len(notes_text) > 10:
                    return notes_text
        
        # Ищем в article после recipe div - часто заметки находятся в <p> в статье
        article = self.soup.find('article')
        if article and recipe_div:
            # Получаем все параграфы в article
            paragraphs = article.find_all('p')
            
            # Ключевые слова для определения заметок
            note_indicators = [
                'može biti', 'važno', 'savjet', 'napomena', 'note', 'tip',
                'preporučuje', 'možete zamijeniti', 'ako radite', 'pazite'
            ]
            
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                if text and len(text) > 20 and len(text) < 500:
                    # Проверяем на индикаторы заметок
                    text_lower = text.lower()
                    if any(indicator in text_lower for indicator in note_indicators):
                        # Извлекаем первое предложение как заметку
                        # Разделяем по точке с пробелом
                        sentences = re.split(r'\.\s+', text)
                        if sentences:
                            first_sentence = sentences[0].strip()
                            if first_sentence and len(first_sentence) > 20:
                                # Добавляем точку в конец если её нет
                                if not first_sentence.endswith('.'):
                                    first_sentence += '.'
                                return first_sentence
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        cuisines = []
        
        # Ищем в WPRM recipe keyword
        keywords = self.soup.find(class_='wprm-recipe-keyword')
        if keywords:
            tags_text = self.clean_text(keywords.get_text())
            if tags_text:
                # Разделяем по запятой и нормализуем
                tags_list = [tag.strip().lower() for tag in tags_text.split(',') if tag.strip()]
        
        # Пробуем JSON-LD для дополнительных тегов
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            # Добавляем keywords из JSON-LD если их еще нет
                            if not tags_list and 'keywords' in item:
                                keywords_text = item['keywords']
                                if isinstance(keywords_text, str):
                                    tags_list = [tag.strip().lower() for tag in keywords_text.split(',') if tag.strip()]
                                elif isinstance(keywords_text, list):
                                    tags_list = [str(tag).strip().lower() for tag in keywords_text if tag]
                            
                            # Добавляем cuisine как тег (переводим на хорватский если это японская кухня)
                            if 'recipeCuisine' in item:
                                cuisine = item['recipeCuisine']
                                if isinstance(cuisine, list):
                                    for c in cuisine:
                                        c_lower = str(c).lower()
                                        if c_lower == 'japanese':
                                            cuisines.append('japanska kuhinja')
                                        else:
                                            cuisines.append(c_lower)
                                elif isinstance(cuisine, str):
                                    if cuisine.lower() == 'japanese':
                                        cuisines.append('japanska kuhinja')
                                    else:
                                        cuisines.append(cuisine.lower())
                            break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Объединяем теги и кухни
        all_tags = tags_list + cuisines
        
        # Удаляем дубликаты сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in all_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в WPRM recipe image
        recipe_image = self.soup.find(class_='wprm-recipe-image')
        if recipe_image:
            img = recipe_image.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обрабатываем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # Recipe с image
                            if item.get('@type') == 'Recipe' and 'image' in item:
                                img = item['image']
                                if isinstance(img, str):
                                    urls.append(img)
                                elif isinstance(img, dict) and 'url' in img:
                                    urls.append(img['url'])
                            # ImageObject
                            elif item.get('@type') == 'ImageObject' and 'url' in item:
                                urls.append(item['url'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
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
    """Обработка HTML файлов из директории preprocessed/bitemybun_com"""
    import os
    
    # Определяем путь к директории с preprocessed файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "bitemybun_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(BitemybunExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python bitemybun_com.py")


if __name__ == "__main__":
    main()
