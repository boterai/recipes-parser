"""
Экстрактор данных рецептов для сайта perenaine.ee
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PerenaineExtractor(BaseRecipeExtractor):
    """Экстрактор для perenaine.ee"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            if 'headline' in item:
                                return self.clean_text(item['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из тега h1 внутри article
        article = self.soup.find('article')
        if article:
            h1 = article.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в article
        article = self.soup.find('article')
        if article:
            paragraphs = article.find_all('p')
            for para in paragraphs:
                text = self.clean_text(para.get_text())
                # Пропускаем очень короткие параграфы
                if text and len(text) > 20:
                    # Берем только первое предложение
                    sentences = text.split('. ')
                    if sentences:
                        return sentences[0] + ('.' if not sentences[0].endswith('.') else '')
        
        return None
    
    def normalize_estonian_word(self, word: str) -> str:
        """
        Нормализация эстонского слова к базовой форме (nominative)
        Упрощенная версия для наиболее распространенных случаев
        """
        # Удаляем скобки и их содержимое
        word = re.sub(r'\([^)]*\)', '', word).strip()
        
        # Словарь распространенных форм
        common_forms = {
            'võid': 'või',
            'suhkrut': 'suhkur',
            'kohupiima': 'kohupiim',
            'munakollast': 'munakollane',
            'nisujahu': 'nisujahu',  # no change
            'küpsetuspulbrit': 'küpsetuspulber',
            'kõrvitsapüree': 'kõrvitsapüree',  # no change
            'riisijahu': 'riisijahu',  # no change
            'šokolaadi': 'šokolaad',
            'tatrajahu': 'tatrajahu',  # no change
            'munakollasid': 'munakollane',
            'mandlilaastud': 'mandlilaastud',  # no change (already nominative plural)
            'kõrvitsa': 'kõrvits',  # genitive -> nominative
            'šokolaadikogumik': 'šokolaad',
            'kõrvitsakogumik': 'kõrvits',
        }
        
        # Проверяем точное совпадение
        if word in common_forms:
            return common_forms[word]
        
        # Общие правила для суффиксов
        original = word
        
        # Удаляем genitive/partitive -d в конце (võid -> või)
        if word.endswith('d') and len(word) > 2:
            word = word[:-1]
        
        # Удаляем partitive -t в конце (suhkrut -> suhkru -> suhkur)
        if word.endswith('t') and len(word) > 2:
            word = word[:-1]
            # Для слов на -ru добавляем r
            if word.endswith('suhkru'):
                word = 'suhkur'
        
        # Удаляем genitive -a в конце (kohupiima -> kohupiim, kõrvitsa -> kõrvits)
        if original.endswith('a') and len(original) > 2 and not original.endswith('oa'):
            word = original[:-1]
            # Для слов заканчивающихся на двойную согласную + a, удаляем одну согласную
            # kõrvitsa -> kõrvits, не kõrvits
        
        # Для прилагательных с -ja (toasooja -> toasoe)
        if 'toasooja' in original:
            word = 'toasoe ' + word.split()[-1] if ' ' in word else 'toasoe või'
        
        return word
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100 g toasooja võid" или "1 dl suhkrut"
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "100 g toasooja võid", "1 dl suhkrut", "2 munakollast"
        # Поддерживаемые единицы: g, ml, dl, l, tl, sl, pcs, kg
        pattern = r'^([\d\s/.,\-]+)?\s*(g|ml|dl|l|tl|sl|pcs|kg|kg|cup|cups|tbsp|tsp)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Удаляем "ca" (circa - приблизительно)
            amount_str = re.sub(r'\bca\b', '', amount_str, flags=re.IGNORECASE).strip()
            # Удаляем "u." (umbes - приблизительно)
            amount_str = re.sub(r'\bu\.?\b', '', amount_str, flags=re.IGNORECASE).strip()
            
            if amount_str:
                # Обработка дробей и диапазонов
                if '-' in amount_str and '/' not in amount_str:
                    # Диапазон (например, "1-2") - берем среднее
                    parts = amount_str.split('-')
                    if len(parts) == 2:
                        try:
                            avg = (float(parts[0]) + float(parts[1])) / 2
                            amount = avg if avg != int(avg) else int(avg)
                        except ValueError:
                            amount = amount_str
                    else:
                        amount = amount_str
                elif '/' in amount_str:
                    # Дробь (например, "1/2")
                    try:
                        parts = amount_str.split()
                        total = 0
                        for part in parts:
                            if '/' in part:
                                num, denom = part.split('/')
                                total += float(num) / float(denom)
                            else:
                                total += float(part)
                        amount = total if total != int(total) else int(total)
                    except (ValueError, ZeroDivisionError):
                        amount = amount_str
                else:
                    try:
                        amount_val = float(amount_str.replace(',', '.'))
                        amount = amount_val if amount_val != int(amount_val) else int(amount_val)
                    except ValueError:
                        amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Нормализация названия к базовой форме
        name = name.strip()
        name = self.normalize_estonian_word(name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все списки ul и ol в article
        article = self.soup.find('article')
        if not article:
            return None
        
        # Находим все списки
        all_lists = article.find_all(['ul', 'ol'])
        
        for lst in all_lists:
            items = lst.find_all('li')
            if not items:
                continue
            
            # Проверяем, является ли этот список списком ингредиентов
            # Список ингредиентов обычно содержит числа и единицы измерения
            first_item_text = items[0].get_text().strip().lower()
            
            # Пропускаем меню и навигационные списки
            if any(word in first_item_text for word in ['avaleht', 'home', 'browse', 'category']):
                continue
            
            # Проверяем, похож ли первый элемент на ингредиент
            if re.search(r'\d+\s*(g|ml|dl|l|tl|sl|pcs|kg)', first_item_text):
                # Это похоже на список ингредиентов
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        parsed = self.parse_ingredient_text(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем параграф с инструкциями в article
        article = self.soup.find('article')
        if not article:
            return None
        
        # Инструкции обычно в нескольких параграфах, которые содержат глаголы в повелительном наклонении
        paragraphs = article.find_all('p')
        
        instruction_paragraphs = []
        
        for para in paragraphs:
            text = para.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Пропускаем короткие параграфы (заголовки типа "Küpsisetaigen:")
            if not text or len(text) < 30:
                continue
            
            # Проверяем наличие характерных слов для инструкций на эстонском
            if any(word in text.lower() for word in ['lisa', 'sega', 'küpseta', 'hõõru', 'klopi', 'võta', 'aseta', 'lõika', 'kata', 'sulata', 'rulli', 'vormi']):
                instruction_paragraphs.append(text)
        
        # Объединяем все найденные параграфы инструкций
        if instruction_paragraphs:
            return ' '.join(instruction_paragraphs)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            if 'articleSection' in item:
                                sections = item['articleSection']
                                
                                # Если это список
                                if isinstance(sections, list) and sections:
                                    # Находим первую полезную категорию (не kogumik)
                                    for section in sections:
                                        section_clean = self.clean_text(section)
                                        # Пропускаем kogumik категории
                                        if 'kogumik' not in section_clean.lower():
                                            # Если это küpsised и это ЕДИНСТВЕННАЯ non-kogumik категория, маппируем в Dessert
                                            non_kogumik_sections = [s for s in sections if 'kogumik' not in self.clean_text(s).lower()]
                                            if section_clean.lower() == 'küpsised' and len(non_kogumik_sections) == 1:
                                                return 'Dessert'
                                            return section_clean
                                    
                                    # Если все категории - kogumik, берем первую
                                    return self.clean_text(sections[0])
                                    
                                elif isinstance(sections, str):
                                    category = self.clean_text(sections)
                                    if category.lower() == 'küpsised':
                                        return 'Dessert'
                                    return category
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из breadcrumbs
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'BreadcrumbList':
                            if 'itemListElement' in item:
                                items = item['itemListElement']
                                # Берем предпоследний элемент (последний - это сам рецепт)
                                if len(items) >= 2:
                                    category_item = items[-2]
                                    if 'name' in category_item:
                                        return self.clean_text(category_item['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        if not text:
            return None
        
        # Паттерны для поиска времени в тексте
        # Ищем числа с "minut", "tund" (час), "h"
        
        # Поиск минут
        minute_pattern = r'(\d+(?:[.,]\d+)?)\s*(?:minut|min)'
        minute_match = re.search(minute_pattern, text, re.IGNORECASE)
        
        # Поиск часов
        hour_pattern = r'(\d+(?:[.,]\d+)?)\s*(?:tund|h\b)'
        hour_match = re.search(hour_pattern, text, re.IGNORECASE)
        
        total_minutes = 0
        
        if hour_match:
            hours = float(hour_match.group(1).replace(',', '.'))
            total_minutes += hours * 60
        
        if minute_match:
            minutes = float(minute_match.group(1).replace(',', '.'))
            total_minutes += minutes
        
        if total_minutes > 0:
            return f"{int(total_minutes)} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте инструкций или заметок
        article = self.soup.find('article')
        if article:
            text = article.get_text()
            # Ищем фразы типа "pooleks tunniks" (полчаса), "30 minutiks"
            if 'pooleks tunniks' in text.lower():
                return "30 minutes"
            
            return self.extract_time_from_text(text, 'prep')
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в article время приготовления
        article = self.soup.find('article')
        if not article:
            return None
        
        text = article.get_text()
        
        # Ищем "ca 20-22 minutit" или "u. 8-10 minutit" в контексте приготовления (küpseta, ahjus)
        cook_pattern = r'(?:küpseta|ahjus).*?(?:ca|u\.?)\s*(\d+(?:-\d+)?)\s*minut'
        match = re.search(cook_pattern, text, re.IGNORECASE)
        
        if match:
            time_str = match.group(1)
            # Если диапазон, берем верхнюю границу
            if '-' in time_str:
                parts = time_str.split('-')
                return f"{parts[-1]} minutes"
            else:
                return f"{time_str} minutes"
        
        # Если не нашли с ca/u., ищем просто после "küpseta"
        simple_pattern = r'küpseta.*?(\d+(?:-\d+)?)\s*minut'
        match = re.search(simple_pattern, text, re.IGNORECASE)
        if match:
            time_str = match.group(1)
            if '-' in time_str:
                parts = time_str.split('-')
                return f"{parts[-1]} minutes"  # Берем максимальное значение
            else:
                return f"{time_str} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Попробуем вычислить из prep_time и cook_time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_minutes = int(re.search(r'\d+', prep).group())
            cook_minutes = int(re.search(r'\d+', cook).group())
            total = prep_minutes + cook_minutes
            return f"{total} minutes"
        elif cook:
            return cook
        elif prep:
            return prep
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Сначала проверяем, есть ли заметки в описании (второе предложение)
        article = self.soup.find('article')
        if not article:
            return None
        
        paragraphs = article.find_all('p')
        
        # Проверяем первый параграф на наличие дополнительной информации
        if paragraphs:
            first_para_text = self.clean_text(paragraphs[0].get_text())
            if first_para_text:
                sentences = first_para_text.split('. ')
                # Если есть второе предложение, которое содержит заметки
                if len(sentences) > 1:
                    second_sentence = sentences[1]
                    # Проверяем, является ли это заметкой (обычно содержит слова о качестве, количестве и т.д.)
                    if any(word in second_sentence.lower() for word in ['tuntava', 'kui kasutad', 'kvaliteet']):
                        return second_sentence + ('.' if not second_sentence.endswith('.') else '')
        
        # Ищем последние параграфы в article, которые не являются инструкциями
        # Заметки обычно о количестве, авторе, источнике и т.д.
        instructions_text = self.extract_instructions()
        
        # Проверяем последние 5 параграфов (в обратном порядке)
        for para in reversed(paragraphs[-5:]):
            text = para.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            if not text or len(text) < 10:
                continue
            
            # Пропускаем параграф, если он является частью инструкций
            if instructions_text and text in instructions_text:
                continue
            
            # Проверяем, содержит ли заметки/советы
            # "Algne retsept" - это заметка, даже если содержит "foto"
            if 'algne retsept' in text.lower():
                return text
            
            # Пропускаем параграфы только с авторством (без другой полезной информации)
            if text.lower().startswith('retsept ja foto:'):
                continue
            
            # Ищем параграфы о количестве, рекомендациях
            if any(word in text.lower() for word in ['kogus', 'tuleb', 'saad', 'sellest kogusest']):
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Пробуем извлечь из JSON-LD articleSection
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            if 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list):
                                    tags_list.extend([self.clean_text(s).lower() for s in sections])
                                elif isinstance(sections, str):
                                    tags_list.append(self.clean_text(sections).lower())
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Преобразуем специфичные категории в более общие теги
        processed_tags = []
        for tag in tags_list:
            # Убираем суффикс "kogumik" и нормализуем слово
            if tag.endswith('kogumik'):
                base = tag[:-7]  # удаляем "kogumik"
                # Нормализуем эстонское слово
                base = self.normalize_estonian_word(base)
                tag = base
            
            # Пропускаем некоторые технические теги, но НЕ пропускаем комбинации типа "nisujahuta küpsetised"
            if 'retseptid' in tag:
                continue
            
            # Пропускаем просто "küpsetised" но оставляем "nisujahuta küpsetised"
            if tag == 'küpsetised':
                continue
            
            processed_tags.append(tag)
        
        # Добавляем "dessert" если есть "küpsised" в исходном списке и мало других тегов
        # НО НЕ добавляем если уже есть специфичные категории
        if any('küpsised' in t for t in tags_list) and len(processed_tags) <= 1:
            processed_tags.append('dessert')
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in processed_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # Ищем ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    urls.append(item['url'])
                                elif 'contentUrl' in item:
                                    urls.append(item['contentUrl'])
                            
                            # Ищем thumbnailUrl в Article
                            if item.get('@type') == 'Article' and 'thumbnailUrl' in item:
                                urls.append(item['thumbnailUrl'])
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
    import os
    # Обрабатываем папку preprocessed/perenaine_ee
    preprocessed_dir = os.path.join("preprocessed", "perenaine_ee")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PerenaineExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python perenaine_ee.py")


if __name__ == "__main__":
    main()
