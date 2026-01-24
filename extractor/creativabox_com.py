"""
Экстрактор данных рецептов для сайта creativabox.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CreativaboxComExtractor(BaseRecipeExtractor):
    """Экстрактор для creativabox.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в первом h1 (главный заголовок статьи)
        h1_tag = self.soup.find('h1')
        if h1_tag:
            text = h1_tag.get_text(strip=True)
            # Убираем длинные суффиксы после тире (обычно описание)
            # Примеры: "Starinske vanilice koje se tope u ustima – proveren domaći recept"
            # -> "Starinske vanilice"
            text = re.sub(r'\s+[–—-]\s+.+$', '', text)
            # Также убираем фразы типа "koje se tope u ustima"
            text = re.sub(r'\s+koje\s+.+$', '', text)
            # Убираем "brz i jednostavan recept za X minuta"
            text = re.sub(r'\s+brz\s+i\s+jednostavan.+$', '', text, flags=re.I)
            return self.clean_text(text)
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            headline = item['headline']
                            # Убираем суффиксы
                            headline = re.sub(r'\s+[–—-]\s+.+$', '', headline)
                            headline = re.sub(r'\s+koje\s+.+$', '', headline)
                            headline = re.sub(r'\s+brz\s+i\s+jednostavan.+$', '', headline, flags=re.I)
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый значимый параграф (после заголовка, но до "Sastojci")
        p_tags = self.soup.find_all('p')
        
        # Собираем кандидатов на описание
        candidates = []
        
        for p in p_tags:
            text = p.get_text(strip=True)
            # Пропускаем короткие параграфы и заголовки секций
            if not text or len(text) < 30:
                continue
            # Пропускаем параграфы с ингредиентами (начинаются с SASTOJCI:)
            if re.match(r'^sastojci:', text, re.I):
                break
            # Пропускаем параграфы с ингредиентами (содержат цифры и единицы измерения в начале)
            if re.match(r'^\d+\s*(g|kg|ml|l|kašik|kesic|limun)', text, re.I):
                continue
            # Пропускаем заголовки секций
            if text.lower() in ['sastojci', 'priprema:', 'priprema', 'saveti', 'napomene']:
                continue
            # Пропускаем параграфы с информацией о сайте
            if 'creativabox' in text.lower() or 'consent' in text.lower():
                continue
            # Добавляем как кандидата
            candidates.append(text)
        
        # Если есть несколько кандидатов, берем тот, который короче (обычно второе предложение)
        if candidates:
            # Ищем параграф, содержащий ключевые слова описания
            for cand in candidates:
                # Ищем описательные предложения
                sentences = re.split(r'[.!?]\s+', cand)
                
                # Ищем предложение с ключевыми словами описания
                for sent in sentences:
                    if re.search(r'(mekani|ukusni|savršeni|brzo|gotovi)', sent, re.I) and len(sent) > 30:
                        # Добавляем точку в конец, если её нет
                        if not sent.endswith('.'):
                            sent += '.'
                        return self.clean_text(sent)
            
            # Если не нашли описательное предложение, берем первое
            return self.clean_text(candidates[0])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Находим все параграфы
        p_tags = self.soup.find_all('p')
        
        # Проверяем, есть ли параграф с "SASTOJCI:" в одну строку
        for p in p_tags:
            text = p.get_text(strip=True)
            if re.match(r'^sastojci:', text, re.I):
                # Извлекаем ингредиенты из одного параграфа с <br/> тегами
                # Заменяем <br/> на новые строки для правильного разделения
                for br in p.find_all('br'):
                    br.replace_with('\n')
                
                # Теперь получаем текст с новыми строками
                text = p.get_text()
                # Убираем заголовок "SASTOJCI:"
                text = re.sub(r'^sastojci:\s*', '', text, flags=re.I)
                # Разделяем по новым строкам
                ingredient_lines = text.split('\n')
                
                for line in ingredient_lines:
                    line = line.strip()
                    if line:
                        parsed = self.parse_ingredient(line)
                        if parsed:
                            ingredients.append(parsed)
                
                return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        # Если не нашли в одном параграфе, ищем отдельные параграфы
        # Флаг для определения, находимся ли в секции ингредиентов
        in_ingredients_section = False
        
        for p in p_tags:
            text = p.get_text(strip=True)
            
            # Начало секции ингредиентов
            if text.lower() == 'sastojci':
                in_ingredients_section = True
                continue
            
            # Конец секции ингредиентов (начало приготовления)
            if text.lower() in ['priprema:', 'priprema']:
                break
            
            # Если мы в секции ингредиентов, парсим ингредиент
            if in_ingredients_section and text:
                parsed = self.parse_ingredient(text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 g masti" или "2 jaja" или "1 čaša pavlake (200 ml)"
            
        Returns:
            dict: {"name": "masti", "amount": 250, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения: количество + единица + название
        # Примеры: 
        # "250 g masti"
        # "2 jaja"
        # "3 kašike šećera"
        # "sok od 1 limuna"
        # "1 čaša pavlake (200 ml)" - извлекаем 200 ml
        # "3 čaše brašna (oko 450 g)" - извлекаем 450 g
        
        # Специальный случай: "sok od 1 limuna"
        special_match = re.match(r'^([^\d]+)\s+od\s+(\d+)\s+(.+)$', text, re.I)
        if special_match:
            name_part, amount, unit = special_match.groups()
            return {
                "name": name_part.strip(),
                "amount": int(amount),
                "units": unit.strip()
            }
        
        # Специальный случай: "1 čaša pavlake (200 ml)" или "3 čaše brašna (oko 450 g)"
        # Извлекаем число из скобок, которое более точное
        bracket_match = re.search(r'\((?:oko\s+)?(\d+)\s*(ml|g|kg|l|kašičica|kašika|kesica)\)', text, re.I)
        if bracket_match:
            amount_in_bracket = int(bracket_match.group(1))
            unit_in_bracket = bracket_match.group(2).lower()
            # Убираем скобки из текста
            text_without_bracket = re.sub(r'\s*\([^)]+\)', '', text)
            # Парсим оставшуюся часть для получения имени
            name_match = re.match(r'^\d+[.,/\d\s]*\s*(?:čaš[ea]?|kašik[ea]?|kašičic[ea]?|kesic[ea]?)?\s*(.+)$', text_without_bracket, re.I)
            if name_match:
                name = name_match.group(1).strip()
                return {
                    "name": name,
                    "amount": amount_in_bracket,
                    "units": unit_in_bracket
                }
        
        # Обычный паттерн: количество + опционально единица + название
        pattern = r'^(\d+[.,/\d\s]*)\s*(g|kg|ml|l|kašik[ea]?|kašičic[ea]?|kesic[ea]?|limun[a]?|čaš[ea]?)?\s*(.+?)(?:\s*\([^)]+\))?$'
        
        match = re.match(pattern, text, re.I)
        
        if not match:
            # Если нет количества, проверяем, есть ли текст в скобках (за филование, за посипање...)
            # Это ингредиент без количества
            if '(' in text and ')' in text:
                name = re.sub(r'\s*\([^)]+\)', '', text).strip()
                unit_match = re.search(r'\((.+)\)', text)
                unit = unit_match.group(1) if unit_match else None
                return {
                    "name": name,
                    "amount": None,
                    "units": unit
                }
            # Пропускаем, если это не похоже на ингредиент
            return None
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                try:
                    num, denom = amount_str.split('/')
                    amount = float(num) / float(denom)
                except:
                    amount = float(amount_str.replace(',', '.'))
            else:
                amount = int(amount_str.replace(',', '.').split('.')[0]) if '.' not in amount_str else float(amount_str.replace(',', '.'))
        
        # Очистка названия
        name = name.strip() if name else None
        unit = unit.strip() if unit else None
        
        # Не преобразуем чаши, если не было скобок с точным количеством
        # Просто оставляем как "čaša" если это было в оригинале
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Находим все параграфы
        p_tags = self.soup.find_all('p')
        
        # Флаг для определения, находимся ли в секции приготовления
        in_instructions_section = False
        found_sastojci = False
        
        for p in p_tags:
            text = p.get_text(strip=True)
            
            # Отмечаем, что прошли секцию ингредиентов
            if re.match(r'^sastojci', text, re.I):
                found_sastojci = True
                continue
            
            # Начало секции приготовления
            if text.lower() in ['priprema:', 'priprema']:
                in_instructions_section = True
                continue
            
            # Конец секции инструкций (начало советов)
            if re.match(r'^saveti|napomene|tips|saveti za', text, re.I) and len(text) < 100:
                break
            
            # Пропускаем параграфы с информацией о сайте
            if 'creativabox' in text.lower() or 'izvor:' in text.lower() or len(text) > 500:
                break
            
            # Если нашли SASTOJCI, но нет явного "Priprema:", 
            # то следующий параграф после ингредиентов - это инструкции
            if found_sastojci and not in_instructions_section:
                # Пропускаем короткие параграфы и заголовки
                if len(text) > 20 and not re.match(r'^\d+\s*(g|ml|kg)', text):
                    in_instructions_section = True
            
            # Если мы в секции приготовления, добавляем инструкцию
            if in_instructions_section and text and len(text) > 5:
                # Пропускаем параграфы, похожие на ингредиенты
                if re.match(r'^\d+\s*(g|ml|kg|kašik)', text, re.I):
                    continue
                instructions.append(self.clean_text(text))
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Возвращаем первую секцию
                                section = sections[0]
                                # Мапим KUJNA -> Dessert (основываясь на JSON примерах)
                                if section.lower() == 'kujna':
                                    return 'Dessert'
                                return self.clean_text(section)
                            elif isinstance(sections, str):
                                if sections.lower() == 'kujna':
                                    return 'Dessert'
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_paragraphs(self, time_patterns: list) -> Optional[str]:
        """
        Извлечение времени из параграфов
        
        Args:
            time_patterns: Список паттернов для поиска
        """
        p_tags = self.soup.find_all('p')
        
        for p in p_tags:
            text = p.get_text(strip=True)
            
            for pattern in time_patterns:
                if re.search(pattern, text, re.I):
                    # Извлекаем время в формате "X minutes" или "X minuta"
                    time_match = re.search(r'(\d+)\s*(minut[ea]?s?|min)', text, re.I)
                    if time_match:
                        number = time_match.group(1)
                        return f"{number} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем упоминания времени подготовки в любом параграфе
        p_tags = self.soup.find_all('p')
        
        for p in p_tags:
            text = p.get_text(strip=True)
            # Ищем фразы типа "za samo 15 minuta", "za 15 min", "15 minuta pripreme"
            if re.search(r'(za\s+samo|za|priprem)', text, re.I):
                time_match = re.search(r'(\d+)\s*minut[ae]?s?', text, re.I)
                if time_match:
                    number = time_match.group(1)
                    return f"{number} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени готовки (печења, кувања)
        p_tags = self.soup.find_all('p')
        
        for p in p_tags:
            text = p.get_text(strip=True)
            # Ищем "Pecite ... oko X minuta" или similar
            if re.search(r'pec[ia]|kuva|prži', text, re.I):
                time_match = re.search(r'oko\s+(\d+)\s*minut|(\d+)\s*minut[ae]?', text, re.I)
                if time_match:
                    number = time_match.group(1) or time_match.group(2)
                    return f"{number} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем упоминания общего времени
        patterns = [
            r'ukupno.*?(\d+)\s*minut',
            r'total.*?(\d+)\s*min',
            r'sve\s+u\s+svemu'
        ]
        return self.extract_time_from_paragraphs(patterns)
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Находим все параграфы
        p_tags = self.soup.find_all('p')
        
        # Флаг для определения, находимся ли в секции советов
        in_notes_section = False
        
        for p in p_tags:
            # Заменяем <br/> на новые строки для правильного разделения
            for br in p.find_all('br'):
                br.replace_with('\n')
            
            text = p.get_text(strip=True)
            
            # Начало секции советов
            if re.match(r'^saveti|napomene|tips|savet', text, re.I):
                in_notes_section = True
                # Если это заголовок с двоеточием или короткий, пропускаем
                if len(text) < 50 or text.endswith(':'):
                    continue
            
            # Пропускаем параграфы с информацией о сайте
            if 'creativabox' in text.lower() or 'consent' in text.lower():
                break
            
            # Пропускаем очень длинные параграфы (обычно это не советы, а заключения)
            if len(text) > 300:
                break
            
            # Если мы в секции советов, добавляем заметку
            if in_notes_section and text and len(text) > 10:
                # Убираем фразы типа "Uživajte!", которые часто в конце
                if re.match(r'^(uživajte|prijatno)', text, re.I):
                    continue
                
                # Разделяем на строки (по \n) и затем на предложения
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 10:
                        continue
                    
                    # Разделяем на предложения
                    sentences = re.split(r'[.!?]\s+', line)
                    for sent in sentences:
                        sent = sent.strip()
                        # Пропускаем очень длинные предложения (>200 символов)
                        if len(sent) > 200:
                            continue
                        # Пропускаем предложения с "uživajte", "prijatno"
                        if re.search(r'uživajte|prijatno|isprobajte', sent, re.I):
                            continue
                        if sent and len(sent) > 10:
                            notes.append(sent)
                
                # Берем только первые 2 релевантных предложения
                if len(notes) >= 2:
                    break
        
        if notes:
            result = ' '.join(notes[:2])
            # Добавляем точку в конец, если её нет
            if not result.endswith('.'):
                result += '.'
            return self.clean_text(result)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                # Фильтруем слишком длинные теги (обычно это не релевантные фразы)
                                filtered = [k for k in keywords if len(k) < 30]
                                return ', '.join(filtered[:10]) if filtered else None
                            elif isinstance(keywords, str):
                                return self.clean_text(keywords)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # Ищем thumbnailUrl или image
                        if 'thumbnailUrl' in item:
                            url = item['thumbnailUrl']
                            if url and url not in urls:
                                urls.append(url)
                        
                        if 'image' in item:
                            img = item['image']
                            if isinstance(img, str) and img not in urls:
                                urls.append(img)
                            elif isinstance(img, dict):
                                if '@id' in img:
                                    # Это ссылка, попробуем найти ImageObject
                                    img_id = img['@id']
                                    for other_item in data['@graph']:
                                        if other_item.get('@id') == img_id and other_item.get('@type') == 'ImageObject':
                                            if 'url' in other_item and other_item['url'] not in urls:
                                                urls.append(other_item['url'])
                                            elif 'contentUrl' in other_item and other_item['contentUrl'] not in urls:
                                                urls.append(other_item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        unique_urls = []
        seen = set()
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
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка HTML файлов из директории preprocessed/creativabox_com"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "creativabox_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CreativaboxComExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python creativabox_com.py")


if __name__ == "__main__":
    main()
