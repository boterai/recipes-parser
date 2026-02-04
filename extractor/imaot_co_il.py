"""
Экстрактор данных рецептов для сайта imaot.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ImaotCoIlExtractor(BaseRecipeExtractor):
    """Экстрактор для imaot.co.il"""
    
    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение структурированных данных JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                # Декодируем HTML entities в JSON
                json_text = self.clean_text(script.string)
                data = json.loads(json_text)
                
                # Проверяем, что это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, ValueError) as e:
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'name' in json_ld:
            name = self.clean_text(json_ld['name'])
            if name:
                # Удаляем подзаголовки после запятой
                name = re.split(r',\s*(?:זריזה|מהירה|קלה)', name)[0].strip()
                return name
        
        # Ищем в h1 с id="recipe_information-subject"
        h1 = self.soup.find('h1', id='recipe_information-subject')
        if h1:
            # Ищем span с itemprop="name"
            name_span = h1.find('span', itemprop='name')
            if name_span:
                name = self.clean_text(name_span.get_text())
                # Удаляем подзаголовки
                name = re.split(r',\s*(?:זריזה|מהירה|קלה)', name)[0].strip()
                return name
            # Если нет span, берем весь текст h1
            name = self.clean_text(h1.get_text())
            name = re.split(r',\s*(?:זריזה|מהירה|קלה)', name)[0].strip()
            return name
        
        # Альтернатива - из title
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Удаляем суффиксы
            title_text = re.sub(r'\s*\|.*$', '', title_text)
            title_text = re.split(r',\s*(?:זריזה|מהירה|קלה)', title_text)[0].strip()
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            if desc:
                # Добавляем "עוגה" или другое слово перед описанием, если его нет
                if not any(word in desc[:10] for word in ['עוגה', 'מנה', 'מתכון']):
                    # Проверяем категорию
                    category = self.extract_category()
                    if category and 'עוגות' in category:
                        desc = f"עוגה {desc}"
                return desc
        
        # Ищем p с id="recipe_information-desc"
        desc_p = self.soup.find('p', id='recipe_information-desc')
        if desc_p:
            # Ищем span с itemprop="description"
            desc_span = desc_p.find('span', itemprop='description')
            if desc_span:
                return self.clean_text(desc_span.get_text())
            # Если нет span, берем весь текст p
            return self.clean_text(desc_p.get_text())
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "2 ביצים XL/L" или "כוס סוכר"
            
        Returns:
            dict: {"name": "ביצים", "amount": 2, "units": "XL/L"}
        """
        if not text:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(text).strip()
        
        # Пропускаем инструкции и заметки
        skip_phrases = ['להצלחת', 'תבנית', 'לקישוט:', 'למרנידה', 'שלב']
        if any(phrase in text for phrase in skip_phrases):
            return None
        
        # Паттерн для извлечения: [количество] [единица] [название]
        # Примеры: "2 ביצים XL/L", "כוס סוכר", "חצי כוס שמן"
        
        # Извлекаем количество в начале (числа, дроби, слова типа "חצי")
        amount = None
        units = None
        name = text
        
        # Ищем число в начале строки
        amount_match = re.match(r'^([\d.,/]+)\s+', text)
        if amount_match:
            amount_str = amount_match.group(1)
            # Конвертируем дроби
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except ValueError:
                        amount = amount_str
            else:
                try:
                    # Преобразуем в int если целое число, иначе float
                    amount_val = float(amount_str.replace(',', '.'))
                    amount = int(amount_val) if amount_val.is_integer() else amount_val
                except ValueError:
                    amount = amount_str
            
            # Удаляем количество из текста
            text = text[len(amount_match.group(0)):].strip()
        else:
            # Проверяем на слова типа "חצי" (половина), "כפית" (чайная ложка)
            word_amounts = {
                'חצי': 0.5,
                'רבע': 0.25,
                'שליש': 0.33
            }
            for word, value in word_amounts.items():
                if text.startswith(word + ' '):
                    amount = value
                    text = text[len(word):].strip()
                    break
        
        # Теперь извлекаем единицу измерения (слова в начале перед основным названием)
        # Типичные единицы: כוס, כף, כפית, כפות, כפיות, גרם, קילו, מ"ל и т.д.
        units_patterns = [
            r'^(כוס(?:ות)?|כפ(?:ות|יות|ית)?|כף|גרם|ק"ג|קילו|מ"ל|ליטר|שיניים?|שיני|ענפי?|יחידות?|קטנים?|גדולים?|שלם|גרגירים?|XL/L|L)\s+',
        ]
        
        for pattern in units_patterns:
            units_match = re.match(pattern, text, re.IGNORECASE)
            if units_match:
                units = units_match.group(1).strip()
                text = text[len(units_match.group(0)):].strip()
                break
        
        # Проверяем, может быть единица в конце названия (например, "ביצים XL/L")
        if not units:
            end_units_match = re.search(r'\s+(XL/L|L|M)\.?$', text)
            if end_units_match:
                units = end_units_match.group(1).strip()
                text = text[:end_units_match.start()].strip()
        
        # Оставшийся текст - это название
        name = text.strip()
        
        # Удаляем точки в конце
        if name and name.endswith('.'):
            name = name[:-1].strip()
        
        # Очистка имени - удаляем лишние слова
        name = re.sub(r'\s+או\s+.*$', '', name)  # Убираем "или" и все после
        name = re.sub(r'\s*\(.*?\)\s*', ' ', name)  # Убираем скобки
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeIngredient' in json_ld:
            ingredient_list = json_ld['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ing_text in ingredient_list:
                    if isinstance(ing_text, str):
                        ing_text = self.clean_text(ing_text)
                        if ing_text:
                            parsed = self.parse_ingredient_text(ing_text)
                            if parsed and parsed.get('name'):
                                ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем div с id="recipe_ingri"
        ingr_div = self.soup.find('div', id='recipe_ingri')
        if ingr_div:
            # Ищем все span с itemprop="recipeIngredient"
            ingr_spans = ingr_div.find_all('span', itemprop='recipeIngredient')
            for span in ingr_spans:
                ing_text = self.clean_text(span.get_text())
                if ing_text:
                    parsed = self.parse_ingredient_text(ing_text)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            # Добавляем точку в конце, если её нет
                            if not step_text.endswith('.'):
                                step_text += '.'
                            steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, dict):
                        # Может быть HowToStep
                        step_text = step.get('text') or step.get('name') or ''
                        step_text = self.clean_text(step_text)
                        if step_text:
                            if not step_text.endswith('.'):
                                step_text += '.'
                            steps.append(f"{idx}. {step_text}")
                
                if steps:
                    return '\n'.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем div с классом "recipe_instructions"
        instr_div = self.soup.find('div', class_='recipe_instructions')
        if instr_div:
            # Ищем все параграфы
            paragraphs = instr_div.find_all('p')
            for idx, p in enumerate(paragraphs, 1):
                step_text = self.clean_text(p.get_text())
                if step_text:
                    # Добавляем точку
                    if not step_text.endswith('.'):
                        step_text += '.'
                    # Если уже пронумеровано, не добавляем номер
                    if not re.match(r'^\d+\.', step_text):
                        step_text = f"{idx}. {step_text}"
                    steps.append(step_text)
        
        return '\n'.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeCategory' in json_ld:
            category = self.clean_text(json_ld['recipeCategory'])
            if category:
                return category
        
        # Ищем в breadcrumb
        # Ищем span с itemprop="recipeCategory"
        category_span = self.soup.find('span', itemprop='recipeCategory')
        if category_span:
            return self.clean_text(category_span.get_text())
        
        # Ищем в хлебных крошках
        breadcrumb = self.soup.find('ol', class_='breadcrumb')
        if not breadcrumb:
            breadcrumb = self.soup.find('ul', class_='breadcrumb')
        
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Берем последнюю ссылку перед текущей страницей
            for link in reversed(links):
                link_text = self.clean_text(link.get_text())
                if link_text and link_text not in ['עמוד הבית', 'כל המתכונים', 'ספרי מתכונים']:
                    return link_text
        
        return None
    
    def extract_time(self, time_key: str) -> Optional[str]:
        """
        Извлечение времени из JSON-LD
        
        Args:
            time_key: Ключ времени ('prepTime', 'cookTime', 'totalTime')
        """
        json_ld = self.extract_json_ld()
        if not json_ld or time_key not in json_ld:
            return None
        
        time_value = json_ld[time_key]
        if not time_value:
            return None
        
        # Очищаем и возвращаем
        time_value = self.clean_text(str(time_value))
        
        # Если время "0 דקות" (0 минут), возвращаем None
        if time_value in ['0 דקות', '0 minutes', '0']:
            return None
        
        return time_value
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем из JSON-LD
        cook_time = self.extract_time('cookTime')
        if cook_time:
            return cook_time
        
        # Если в JSON-LD нет, ищем в инструкциях
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "אופים 35 דקות" или "לתנור ל-3 שעות"
            time_patterns = [
                r'אופים\s+(\d+)\s+דקות',
                r'ל(?:פחות)?\s+(\d+)\s+שעות',
                r'(\d+)\s+minutes',
                r'(\d+)\s+hours?'
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, instructions)
                if match:
                    time_value = match.group(1)
                    # Определяем единицу измерения
                    if 'שעות' in match.group(0) or 'hour' in match.group(0):
                        return f"{int(time_value) * 60} minutes"
                    else:
                        return f"{time_value} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в инструкциях секции с "טיפ:" или "הערה:"
        instructions = self.extract_instructions()
        if instructions:
            # Ищем строки, начинающиеся с "טיפ:" или содержащие совет
            lines = instructions.split('\n')
            notes = []
            for line in lines:
                if 'טיפ:' in line or 'הערה:' in line:
                    # Удаляем номер и префикс
                    note = re.sub(r'^\d+\.\s*', '', line)
                    note = re.sub(r'^טיפ:\s*', '', note)
                    note = re.sub(r'^הערה:\s*', '', note)
                    note = self.clean_text(note)
                    if note:
                        notes.append(note)
            
            if notes:
                return ' '.join(notes)
        
        # Ищем в HTML секции с классом "tip" или "note"
        tip_divs = self.soup.find_all(['div', 'p'], class_=re.compile(r'tip|note', re.I))
        if tip_divs:
            notes = []
            for div in tip_divs:
                note_text = self.clean_text(div.get_text())
                if note_text:
                    notes.append(note_text)
            
            if notes:
                return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join([self.clean_text(str(k)) for k in keywords if k])
        
        # Ищем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'image' in json_ld:
            image_data = json_ld['image']
            if isinstance(image_data, str):
                urls.append(image_data)
            elif isinstance(image_data, list):
                urls.extend([img for img in image_data if isinstance(img, str)])
            elif isinstance(image_data, dict):
                if 'url' in image_data:
                    urls.append(image_data['url'])
        
        # Ищем img с itemprop="image"
        img_tags = self.soup.find_all('img', itemprop='image')
        for img in img_tags:
            src = img.get('src')
            if src:
                # Добавляем полный URL если нужно
                if src.startswith('/'):
                    src = f"https://imaot.co.il{src}"
                urls.append(src)
        
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
    """Обработка директории preprocessed/imaot_co_il"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "imaot_co_il"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ImaotCoIlExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python imaot_co_il.py")


if __name__ == "__main__":
    main()
