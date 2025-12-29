"""
Экстрактор данных рецептов для сайта imommy.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ImommyGrExtractor(BaseRecipeExtractor):
    """Экстрактор для imommy.gr"""
    
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
            # Убираем суффикс " | imommy"
            title = re.sub(r'\s+\|\s+imommy.*$', '', title, flags=re.IGNORECASE)
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
    
    def _parse_ingredient_line(self, line: str) -> List[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат.
        Может вернуть несколько ингредиентов если они слиплись.
        
        Примеры:
        "500 γρ. μοσχαρίσιο κιμά" -> [{"name": "μοσχαρίσιο κιμά", "units": "г", "amount": 500}]
        "2 αυγά" -> [{"name": "αυγά", "units": null, "amount": 2}]
        "αλάτι" -> [{"name": "αλάτι", "units": null, "amount": null}]
        "αλάτιπιπέρι" -> [{"name": "αλάτι", "units": null, "amount": null}, {"name": "πιπέρι", "units": null, "amount": null}]
        "πράσοχυμός από 2 λεμόνια" -> [{"name": "πράσο", ...}, {"name": "χυμός από λεμόνια", "amount": 2}]
        """
        if not line:
            return []
        
        line = self.clean_text(line)
        
        # Словарь для преобразования греческих единиц измерения
        unit_mapping = {
            'γρ.': 'г',
            'γρ': 'г',
            'gr': 'г',
            'γραμμάρια': 'г',
            'ml': 'ml',
            'λίτρο': 'λίτρο',
            'λίτρα': 'λίτρο',
            'κ.σ.': 'κ.σ.',
            'κουτ. σούπας': 'κ.σ.',
            'κ.γ.': 'κ.γ.',
            'κουτ. γλυκού': 'κ.γ.',
            'ματσάκι': 'ματσάκι',
            'φλιτζάνι': 'φλιτζάνι',
            'φλ.': 'φλιτζάνι',
        }
        
        # Список известных ингредиентов без количества (обычно специи)
        standalone_ingredients = ['αλάτι', 'πιπέρι', 'ζάχαρη', 'αλεύρι']
        
        # Специальные паттерны для распространенных случаев
        # Например: "πράσοχυμός από 2 λεμόνια" - разделяем перед "χυμός"
        special_patterns = [
            (r'(πράσο)(χυμός\s+από\s+\d+)', r'\1SPLIT\2'),
            (r'(κορν\s+φλάουρ)(αλάτι)', r'\1SPLIT\2'),
            (r'(ζωμός\s+λαχανικών)(αλάτι)', r'\1SPLIT\2'),
        ]
        
        for pattern, replacement in special_patterns:
            line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
        
        # Паттерн: количество + единица измерения + название
        # Примеры: "500 γρ. мука", "2 αυγά", "1/2 ματσάκι άνηθος"
        pattern = r'^([\d./]+)\s*([α-ωά-ώa-z.]+)?\s+(.+)$'
        match = re.match(pattern, line, re.IGNORECASE)
        
        if match:
            amount_str, unit_str, name = match.groups()
            
            # Обработка количества (может быть дробью типа "1/2")
            amount = None
            if amount_str:
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        try:
                            amount = float(parts[0]) / float(parts[1])
                        except ValueError:
                            amount = amount_str
                else:
                    try:
                        amount = int(amount_str) if '.' not in amount_str else float(amount_str)
                    except ValueError:
                        amount = amount_str
            
            # Обработка единицы измерения
            unit = None
            if unit_str:
                unit_str = unit_str.strip()
                # Проверяем, является ли это единицей измерения или частью названия
                # Если единица измерения известна, используем её
                if unit_str in unit_mapping:
                    unit = unit_mapping[unit_str]
                else:
                    # Проверяем известные паттерны
                    for key, value in unit_mapping.items():
                        if unit_str.lower().startswith(key.lower().rstrip('.')):
                            unit = value
                            break
                    
                    # Если не нашли единицу измерения, добавляем к названию
                    if not unit:
                        name = f"{unit_str} {name}"
            
            # Очистка названия
            name = self.clean_text(name)
            # Убираем описания в скобках и дополнительные пояснения
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\s+(τριμμένο|ψιλοκομμένο|κομμένο|κομμένη|λιωμένο).*$', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            # Проверяем на SPLIT маркер
            if 'SPLIT' in name:
                parts = name.split('SPLIT')
                results = []
                
                # Первая часть - с текущим количеством
                if parts[0].strip():
                    results.append({
                        "name": parts[0].strip(),
                        "units": unit,
                        "amount": amount
                    })
                
                # Остальные части - парсим рекурсивно
                for part in parts[1:]:
                    if part.strip():
                        sub_results = self._parse_ingredient_line(part.strip())
                        results.extend(sub_results)
                
                return results
            
            # Проверяем, не слиплись ли в конце несколько ингредиентов без количества
            # Например: "ζωμός λαχανικώναλάτιπιπέρι"
            results = []
            
            # Проверяем на известные слипшиеся ингредиенты
            for standalone in standalone_ingredients:
                if standalone in name:
                    # Разделяем
                    parts = name.split(standalone, 1)  # split only once
                    if len(parts) == 2 and parts[1].strip():
                        # Первая часть - это основной ингредиент с количеством
                        main_name = parts[0].strip() + standalone
                        
                        # Если в первой части есть слипшийся ингредиент, разделяем
                        if len(parts[0].strip()) > 0:
                            # Проверяем, не заканчивается ли первая часть на известное слово
                            clean_main = parts[0].strip()
                            for si in standalone_ingredients:
                                if si in clean_main:
                                    # Разделяем
                                    idx = clean_main.index(si)
                                    if idx > 0:
                                        results.append({
                                            "name": clean_main[:idx+len(si)],
                                            "units": unit,
                                            "amount": amount
                                        })
                                        # Остальное - без количества
                                        remaining = clean_main[idx+len(si):] + parts[1]
                                        for si2 in standalone_ingredients:
                                            if si2 in remaining:
                                                results.append({
                                                    "name": si2,
                                                    "units": None,
                                                    "amount": None
                                                })
                                                remaining = remaining.replace(si2, '', 1).strip()
                                        if remaining:
                                            results.append({
                                                "name": remaining,
                                                "units": None,
                                                "amount": None
                                            })
                                        return results
                        
                        results.append({
                            "name": main_name,
                            "units": unit,
                            "amount": amount
                        })
                        
                        # Вторая часть - слипшиеся ингредиенты без количества
                        remaining = parts[1].strip()
                        for si in standalone_ingredients:
                            if si in remaining:
                                results.append({
                                    "name": si,
                                    "units": None,
                                    "amount": None
                                })
                                remaining = remaining.replace(si, '', 1).strip()
                        
                        if remaining:
                            results.append({
                                "name": remaining,
                                "units": None,
                                "amount": None
                            })
                        
                        return results
            
            return [{
                "name": name,
                "units": unit,
                "amount": amount
            }]
        
        # Если паттерн не совпал, это может быть:
        # 1. Просто название без количества: "αλάτι", "πιπέρι"
        # 2. Несколько слипшихся названий: "αλάτιπιπέρι"
        
        # Проверяем на SPLIT маркер
        if 'SPLIT' in line:
            parts = line.split('SPLIT')
            results = []
            for part in parts:
                if part.strip():
                    sub_results = self._parse_ingredient_line(part.strip())
                    results.extend(sub_results)
            return results
        
        results = []
        remaining_text = line
        
        # Проверяем на слипшиеся ингредиенты
        found_any = True
        while found_any:
            found_any = False
            for standalone in standalone_ingredients:
                if standalone in remaining_text:
                    results.append({
                        "name": standalone,
                        "units": None,
                        "amount": None
                    })
                    remaining_text = remaining_text.replace(standalone, '', 1).strip()
                    found_any = True
                    break
        
        # Если что-то осталось и у нас уже есть результаты, добавляем остаток
        if remaining_text and results:
            results.append({
                "name": remaining_text,
                "units": None,
                "amount": None
            })
        elif remaining_text and not results:
            # Если ничего не нашли, добавляем весь текст как один ингредиент
            name = self.clean_text(remaining_text)
            # Убираем описания
            name = re.sub(r'\([^)]*\)', '', name).strip()
            
            if name and len(name) > 1:
                results.append({
                    "name": name,
                    "units": None,
                    "amount": None
                })
        
        return results if results else []
    
    def _split_ingredients_text(self, text: str) -> List[str]:
        """
        Разделение текста с ингредиентами на отдельные строки
        
        Текст может быть в формате: "500 γρ. μοσχαρίσιο κιμά50 ml ελαιόλαδο2 αυγά..."
        Нужно разделить по началу новой цифры
        """
        # Сначала разделяем по известным разделителям подсекций
        # Например: "Για τη σούπα και το αυγολέμονο:"
        sections = re.split(r'(?:Για|For)\s+[^:]+:', text)
        
        all_ingredients = []
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            # Добавляем пробелы перед числами, если их нет
            # "κιμά50" -> "κιμά 50"
            section = re.sub(r'([α-ωά-ώa-z])(\d)', r'\1 \2', section)
            
            # Добавляем пробелы перед известными словами
            section = re.sub(r'([α-ωά-ώa-z])(χυμός|πράσο|πατάτα|κορν)', r'\1 \2', section, flags=re.IGNORECASE)
            
            # Паттерн для разделения: ищем место, где после буквы/пробела идет цифра
            parts = re.split(r'(?<=[α-ωά-ώa-zΑ-ΩΆ-Ώ\s]|\))(?=\d)', section)
            
            for part in parts:
                part = part.strip()
                if part:
                    all_ingredients.append(part)
        
        return all_ingredients
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        # Найти тело статьи
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Найти секцию с ингредиентами
        ingredients_section_found = False
        ingredients_text_parts = []
        
        for elem in article_body.find_all(['h2', 'h3', 'p', 'ul', 'strong']):
            text = elem.get_text(strip=True)
            
            # Проверяем, является ли это заголовком ингредиентов
            if re.search(r'(Τα\s+υλικά|Υλικά)', text, re.IGNORECASE):
                ingredients_section_found = True
                continue
            
            # Если нашли секцию ингредиентов, собираем текст
            if ingredients_section_found:
                # Останавливаемся на следующем основном заголовке
                if elem.name in ['h2', 'h3']:
                    # Но не останавливаемся на подзаголовках внутри ингредиентов
                    if not re.search(r'(για|For|σούπα|αυγολέμονο)', text, re.IGNORECASE):
                        break
                
                # Собираем текст из <p> и <ul> элементов
                if elem.name in ['p', 'ul'] and text:
                    ingredients_text_parts.append(text)
        
        if not ingredients_text_parts:
            return None
        
        # Объединяем все части
        full_text = ' '.join(ingredients_text_parts)
        
        # Разделяем на отдельные ингредиенты
        ingredient_lines = self._split_ingredients_text(full_text)
        
        # Парсим каждый ингредиент
        ingredients = []
        for line in ingredient_lines:
            parsed_list = self._parse_ingredient_line(line)
            if parsed_list:
                ingredients.extend(parsed_list)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Найти тело статьи
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Найти секцию с инструкциями
        instructions_section_found = False
        instructions_parts = []
        
        for elem in article_body.find_all(['h2', 'h3', 'p', 'ol', 'ul']):
            text = elem.get_text(strip=True)
            
            # Проверяем, является ли это заголовком инструкций
            # Может быть как заголовок h2/h3, так и параграф с двоеточием
            if re.search(r'(Η\s+διαδικασία|Εκτέλεση|Παρασκευή|Οδηγίες)', text, re.IGNORECASE):
                instructions_section_found = True
                # Пропускаем сам заголовок
                continue
            
            # Если нашли секцию инструкций, собираем текст
            if instructions_section_found:
                # Останавливаемся на следующем заголовке (но не на первом - это был заголовок инструкций)
                if elem.name in ['h2', 'h3']:
                    break
                
                # Собираем текст из параграфов и списков
                if elem.name in ['p', 'ol', 'ul'] and text:
                    # Для списков - извлекаем элементы списка
                    if elem.name in ['ol', 'ul']:
                        list_items = elem.find_all('li')
                        for i, li in enumerate(list_items, 1):
                            item_text = self.clean_text(li.get_text())
                            if item_text:
                                # Добавляем нумерацию если её нет
                                if not re.match(r'^\d+\.', item_text):
                                    item_text = f"{i}. {item_text}"
                                instructions_parts.append(item_text)
                    else:
                        cleaned = self.clean_text(text)
                        if cleaned:
                            instructions_parts.append(cleaned)
        
        return ' '.join(instructions_parts) if instructions_parts else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На данный момент в примерах нет информации о питательности
        # Можно попробовать найти в тексте, но скорее всего её нет
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # По умолчанию для рецептов с imommy.gr используем Main Course
        # так как это сайт о материнстве и семейных рецептах
        # Проверяем breadcrumbs - ищем "Συνταγές" или другие категории
        breadcrumbs = self.soup.find_all('a', href=re.compile(r'/category/'))
        
        # Ищем категорию, которая связана с едой/рецептами
        food_categories = []
        for bc in breadcrumbs:
            text = bc.get_text(strip=True)
            # Проверяем, является ли это категорией еды
            if text and re.search(r'(Συνταγές|Main|Dessert|Breakfast|Appetizer)', text, re.IGNORECASE):
                food_categories.append(text)
        
        # Также проверяем meta article:section
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            section = self.clean_text(article_section['content'])
            if section and re.search(r'(Συνταγές|recipe)', section, re.IGNORECASE):
                food_categories.append(section)
        
        # Возвращаем первую найденную категорию или дефолтное значение
        if food_categories:
            category = food_categories[0]
            # Переводим на английский, если нужно
            if 'Συνταγές' in category or 'κύριο' in category.lower():
                return 'Main Course'
            return category
        
        # Если категория рецепта, по умолчанию Main Course
        return 'Main Course'
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте статьи упоминания времени подготовки
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if article_body:
            text = article_body.get_text()
            # Ищем паттерн "προετοιμασία X λεπτά" или подобные
            prep_patterns = [
                r'προετοιμασ[ίι][αά].*?(\d+)\s*(λεπτά|λεπτό|minutes?)',
                r'(\d+)\s*(λεπτά|λεπτό|minutes?).*?προετοιμασ',
            ]
            
            for pattern in prep_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    # Находим группу с числом
                    groups = match.groups()
                    for i, g in enumerate(groups):
                        if g and g.isdigit():
                            return f"{g} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте статьи упоминания времени готовки
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if article_body:
            text = article_body.get_text()
            # Ищем паттерны времени приготовления
            # Например: "Σε 15 λεπτά είναι έτοιμα"
            cook_patterns = [
                r'(?:Σε|σε|In|in)\s+(\d+)\s*(λεπτά|λεπτό|minutes?|mins?).*?(?:έτοιμ|ready)',
                r'(?:μαγείρεμα|ψήσιμο|cooking|baking).*?(\d+)\s*(λεπτά|λεπτό|ώρα|minutes?|hours?)',
            ]
            
            for pattern in cook_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    number = match.group(1)
                    unit = match.group(2).lower()
                    
                    if 'λεπτ' in unit or 'min' in unit:
                        return f"{number} minutes"
                    elif 'ώρ' in unit or 'hour' in unit:
                        return f"{number} hours"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Можно попробовать найти в тексте или вычислить из prep_time + cook_time
        # Но в примерах такой информации нет явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Ищем заголовки с советами/примечаниями
        notes_section_found = False
        notes_parts = []
        
        for elem in article_body.find_all(['h2', 'h3', 'p']):
            text = elem.get_text(strip=True)
            
            # Проверяем, является ли это заголовком с советами
            if re.search(r'(Συμβουλ[ήε]|Σημειώσ|Tips|Notes)', text, re.IGNORECASE):
                notes_section_found = True
                continue
            
            # Если нашли секцию с советами, собираем текст
            if notes_section_found:
                # Останавливаемся на следующем заголовке
                if elem.name in ['h2', 'h3']:
                    break
                
                if elem.name == 'p' and text:
                    notes_parts.append(self.clean_text(text))
        
        return ' '.join(notes_parts) if notes_parts else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # На данный момент в примерах нет тегов
        # Можно попробовать извлечь из meta keywords или других мест
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            return self.clean_text(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем thumbnailUrl в microdata
        thumbnail = self.soup.find(attrs={'itemprop': 'thumbnailUrl'})
        if thumbnail:
            url = thumbnail.get('content') or thumbnail.get('src')
            if url:
                urls.append(url)
        
        # 3. Ищем изображения в теле статьи
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if article_body:
            images = article_body.find_all('img', src=True)
            for img in images[:3]:  # Ограничиваем до 3 изображений
                src = img.get('src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Точка входа для обработки HTML-файлов imommy.gr"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "imommy_gr")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ImommyGrExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python imommy_gr.py")


if __name__ == "__main__":
    main()
