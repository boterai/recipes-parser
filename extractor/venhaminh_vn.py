"""
Экстрактор данных рецептов для сайта venhaminh.vn
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VenhaMinhExtractor(BaseRecipeExtractor):
    """Экстрактор для venhaminh.vn"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем суффиксы типа "- Venhaminh.vn"
            title = re.sub(r'\s*[-–]\s*Venhaminh\.vn.*$', '', title, flags=re.IGNORECASE)
            # Убираем префиксы типа "Cách Nấu", "Cách Làm"
            title = re.sub(r'^Cách\s+(Nấu|Làm|Chế\s+Biến)\s+', '', title, flags=re.IGNORECASE)
            # Убираем префиксы "Món"
            title = re.sub(r'^Món\s+', '', title, flags=re.IGNORECASE)
            # Убираем модификаторы "Ngon Nhất"
            title = re.sub(r'\s+Ngon\s+Nhất\b', '', title, flags=re.IGNORECASE)
            # Убираем суффиксы типа "Thơm Ngon Đậm Đà", "Cho Gia Đình Việt" и т.д.
            title = re.sub(r'\s+(?:Thơm\s+Ngon\s+Đậm\s+Đà|Thơm\s+Ngon|Cho\s+Gia\s+Đình.*|Tại\s+Nhà.*|Chuẩn\s+Vị.*)$', '', title, flags=re.IGNORECASE)
            return title.strip()
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–]\s*Venhaminh\.vn.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Cách\s+(Nấu|Làm|Chế\s+Biến)\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Món\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+Ngon\s+Nhất\b', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+(?:Thơm\s+Ngon\s+Đậm\s+Đà|Thơm\s+Ngon|Cho\s+Gia\s+Đình.*|Tại\s+Nhà.*|Chuẩn\s+Vị.*)$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title).strip()
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*[-–]\s*Venhaminh\.vn.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Cách\s+(Nấu|Làm|Chế\s+Biến)\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Món\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+Ngon\s+Nhất\b', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+(?:Thơm\s+Ngon\s+Đậm\s+Đà|Thơm\s+Ngon|Cho\s+Gia\s+Đình.*|Tại\s+Nhà.*|Chuẩn\s+Vị.*)$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title).strip()
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Берем только первое предложение для краткости
            if '.' in desc:
                desc = desc.split('.')[0] + '.'
            return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if '.' in desc:
                desc = desc.split('.')[0] + '.'
            return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем секцию с заголовком "Chuẩn Bị Nguyên Liệu" или "nguyên liệu"
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip()
            if 'Chuẩn Bị Nguyên Liệu' in heading_text or 'nguyên liệu' in heading_text.lower():
                # Находим следующий ul после этого заголовка
                next_ul = heading.find_next('ul')
                if next_ul:
                    items = next_ul.find_all('li')
                    for item in items:
                        # Извлекаем текст ингредиента
                        strong = item.find('strong')
                        
                        if strong:
                            # Формат 1: <strong>Название:</strong> описание
                            name = self.clean_text(strong.get_text().replace(':', '').strip())
                            
                            # Остальной текст содержит количество и единицы
                            full_text = item.get_text()
                            desc_text = full_text.replace(strong.get_text(), '', 1).strip()
                            desc_text = self.clean_text(desc_text)
                            
                            # Парсим количество и единицы
                            parsed = self._parse_ingredient_details(name, desc_text)
                            if parsed:
                                ingredients.append(parsed)
                        else:
                            # Формат 2: количество+название: описание (например "500g cua đồng: ...")
                            full_text = self.clean_text(item.get_text())
                            
                            # Разделяем по двоеточию
                            if ':' in full_text:
                                ingredient_part = full_text.split(':')[0].strip()
                            else:
                                ingredient_part = full_text.split('.')[0].strip() if '.' in full_text else full_text
                            
                            # Парсим ингредиент
                            parsed = self._parse_full_ingredient_text(ingredient_part)
                            if parsed:
                                ingredients.append(parsed)
                    
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _parse_full_ingredient_text(self, text: str) -> Optional[Dict]:
        """
        Парсинг полного текста ингредиента вида "500g cua đồng" или "1 củ tỏi lớn"
        
        Args:
            text: Полный текст ингредиента с количеством и названием
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not text:
            return None
        
        text = text.strip()
        amount = None
        units = None
        name = text  # По умолчанию - весь текст
        
        # Паттерны для различных форматов:
        # "500g cua đồng", "1 củ tỏi lớn", "1-2 quả ớt", "200-300g thịt bò"
        patterns = [
            # Число + единица + название (500g cua đồng)
            r'^(\d+(?:-\d+)?(?:\.\d+)?)\s*(g|kg|ml|l|grams?)\s+(.+)$',
            # Число + единица слово + название (1 củ tỏi lớn, 1-2 quả ớt)
            r'^(\d+(?:-\d+)?)\s+(củ|quả|thìa|muỗng|bát|cái|miếng)\s+(.+)$',
            # Число + "thìa canh/cà phê" + название
            r'^(\d+(?:[.,]\d+)?)\s+(thìa\s+(?:canh|cà\s+phê)|muỗng\s+(?:canh|cà\s+phê))\s+(.+)$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1)
                units = match.group(2).strip()
                name = match.group(3).strip()
                break
        
        # Если не нашли паттерн, но есть специальные ключевые слова
        if amount is None:
            if any(kw in text.lower() for kw in ['lượng đủ', 'tùy ý', 'một ít', 'vừa đủ']):
                # Извлекаем название без количественных слов
                name_match = re.search(r'(?:lượng đủ|tùy ý|một ít|vừa đủ)\s+(?:để|cho)?\s*(.+)', text.lower())
                if name_match:
                    name = name_match.group(1).strip()
                else:
                    # Просто убираем квантификаторы
                    name = re.sub(r'\b(?:lượng đủ|tùy ý|một ít|vừa đủ)\b', '', text, flags=re.IGNORECASE).strip()
                units = 'lượng đủ' if 'lượng đủ' in text.lower() else None
        
        return {
            "name": name,
            "units": units,
            "amount": self._convert_amount(amount) if amount else None
        }
    
    def _parse_ingredient_details(self, name: str, description: str) -> Optional[Dict]:
        """
        Парсинг деталей ингредиента из описания
        
        Args:
            name: Название ингредиента
            description: Описание с количеством и единицами
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not name:
            return None
        
        amount = None
        units = None
        
        # Удаляем "(tùy chọn)" из имени
        name = re.sub(r'\s*\(tùy\s+chọn\)', '', name, flags=re.IGNORECASE).strip()
        
        # Попытка извлечь количество и единицы из описания
        # Шаблоны для количества: "1kg", "150-200g", "1-2 củ", "Khoảng 1kg"
        
        # Очищаем описание от лишнего текста
        desc_clean = description.lower()
        
        # Паттерн для извлечения количества и единиц
        # Примеры: "1kg", "150-200g", "200-300g", "1-2 củ", "khoảng 1kg", "1 bát con (khoảng 150-200g)"
        
        # Сначала пытаемся найти в скобках
        bracket_match = re.search(r'\(khoảng\s+(\d+(?:-\d+)?)\s*([a-zđệếô\s]+)\)', desc_clean)
        if bracket_match:
            amount = bracket_match.group(1)
            units = bracket_match.group(2).strip()
        else:
            # Обычные паттерны
            patterns = [
                r'(?:khoảng\s+)?(\d+(?:-\d+)?(?:\.\d+)?)\s*(kg|g|ml|l|củ|quả|thìa\s+canh|thìa\s+cà\s+phê|muỗng\s+canh|muỗng\s+cà\s+phê|grams?|lít|bát(?:\s+con)?|củ\s+lớn|củ\s+nhỏ)',
                r'(\d+(?:-\d+)?(?:\.\d+)?)\s*-?\s*(kg|g|ml|l|củ|quả|thìa|muỗng|grams?|lít|bát)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, desc_clean)
                if match:
                    amount = match.group(1)
                    units = match.group(2).strip()
                    # Убираем " con" из "bát con"
                    units = re.sub(r'\s+con$', '', units)
                    break
        
        # Если не нашли количество, но есть ключевые слова
        if not amount:
            # Проверяем на специальные случаи
            if 'lượng đủ' in desc_clean or 'tùy chọn' in desc_clean:
                amount = None
                units = 'lượng đủ' if 'lượng đủ' in desc_clean else None
            elif 'một ít' in desc_clean:
                amount = None
                units = 'một ít'
        
        return {
            "name": name,
            "units": units,
            "amount": self._convert_amount(amount) if amount else None
        }
    
    def _convert_amount(self, amount_str: str) -> any:
        """Конвертирует строку количества в число или оставляет как строку"""
        if not amount_str:
            return None
        
        # Если это диапазон (например "150-200"), оставляем как строку
        if '-' in amount_str:
            return amount_str
        
        # Пытаемся преобразовать в число
        try:
            # Если есть точка, возвращаем float
            if '.' in amount_str:
                return float(amount_str)
            # Иначе int
            return int(amount_str)
        except ValueError:
            # Если не получилось, возвращаем как строку
            return amount_str
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем секцию с заголовком "Các Bước Thực Hiện" или "Hướng Dẫn"
        for heading in self.soup.find_all(['h2', 'h3']):
            heading_text = heading.get_text().strip()
            if 'Các Bước Thực Hiện' in heading_text or 'Hướng Dẫn' in heading_text:
                # Ищем все h4 заголовки (Bước 1, Bước 2, etc.) после этого заголовка
                current = heading.find_next_sibling()
                step_num = 1
                
                while current:
                    # Если встретили новый h2 или h3, останавливаемся
                    if current.name in ['h2', 'h3'] and current != heading:
                        break
                    
                    # Если это h4 с описанием шага
                    if current.name == 'h4':
                        step_title = self.clean_text(current.get_text())
                        # Убираем нумерацию, если есть (например "1. ", "Bước 1:")
                        step_title = re.sub(r'^(?:Bước\s+)?\d+[\.:]?\s*', '', step_title)
                        # Делаем первую букву строчной для соответствия референсу
                        if step_title:
                            step_title = step_title[0].lower() + step_title[1:] if len(step_title) > 1 else step_title.lower()
                        
                        # Убираем капитализацию в середине (Title Case -> normal case)
                        # Сохраняем только первую букву каждого слова строчной
                        words = step_title.split()
                        normalized_words = []
                        for i, word in enumerate(words):
                            if i == 0:
                                # Первое слово - с маленькой буквы
                                normalized_words.append(word[0].lower() + word[1:].lower() if len(word) > 1 else word.lower())
                            else:
                                # Остальные слова - полностью маленькие
                                normalized_words.append(word.lower())
                        step_title = ' '.join(normalized_words)
                        
                        # Добавляем точку в конце, если её нет
                        if not step_title.endswith('.'):
                            step_title += '.'
                        
                        instructions.append(f"{step_num}. {step_title}")
                        step_num += 1
                    
                    current = current.find_next_sibling()
                
                if instructions:
                    break
        
        # Если не нашли инструкции через заголовки, попробуем найти пронумерованный список
        if not instructions:
            for ol in self.soup.find_all('ol'):
                # Проверяем, что это похоже на список инструкций
                items = ol.find_all('li', recursive=False)
                if len(items) >= 3:  # Если есть хотя бы 3 шага
                    for idx, item in enumerate(items, 1):
                        text = self.clean_text(item.get_text())
                        # Берем первое предложение или первые 150 символов
                        if '.' in text:
                            text = text.split('.')[0] + '.'
                        if len(text) > 150:
                            text = text[:150] + '...'
                        # Делаем первую букву строчной
                        if text:
                            text = text[0].lower() + text[1:] if len(text) > 1 else text.lower()
                        # Добавляем точку в конце, если её нет
                        if not text.endswith('.') and not text.endswith('...'):
                            text += '.'
                        instructions.append(f"{idx}. {text}")
                    break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # В примерах категория всегда "Main Course"
        # Можно попробовать извлечь из breadcrumbs или meta
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        # По умолчанию возвращаем Main Course для вьетнамских рецептов
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в HTML секцию с ингредиентами где часто упоминается время ướp (маринования)
        # или ищем в тексте упоминания времени подготовки
        
        text = self.soup.get_text()
        
        # Ищем паттерны времени подготовки/маринования
        patterns = [
            r'(?:chuẩn\s+bị|prep|preparation)[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?|mins?)',
            r'thời\s+gian\s+chuẩn\s+bị[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?)',
            r'(?:ướp|ngấm\s+gia\s+vị).*?khoảng\s+(\d+(?:-\d+)?)\s*phút',
            r'khoảng\s+(\d+(?:-\d+)?)\s*phút.*?(?:ướp|ngấm\s+gia\s+vị)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_val = match.group(1)
                # Если диапазон, берем максимальное значение (более реалистичное)
                if '-' in time_val:
                    time_val = time_val.split('-')[1]
                return f"{time_val} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        text = self.soup.get_text()
        
        patterns = [
            r'thời\s+gian\s+nấu\s+khoảng\s+(\d+(?:-\d+)?)\s*phút',
            r'nấu\s+cho\s+đến\s+khi.*?khoảng\s+(\d+(?:-\d+)?)\s*phút',
            r'(?:nấu|cook|cooking)[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?|mins?)',
            r'thời\s+gian\s+nấu[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?)',
            r'(?:hầm|ninh).*?khoảng\s+(\d+(?:-\d+)?)\s*(?:phút|minutes)',
            r'khoảng\s+(\d+(?:-\d+)?)\s*phút.*?(?:nấu|hầm|ninh)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_val = match.group(1)
                return f"{time_val} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        text = self.soup.get_text()
        
        patterns = [
            r'(?:tổng|total|ready)[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?|mins?)',
            r'thời\s+gian\s+(?:tổng|hoàn\s+thành)[:\s]*(\d+(?:-\d+)?)\s*(?:phút|minutes?)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_val = match.group(1)
                return f"{time_val} minutes"
        
        # Если есть prep_time и cook_time, можем сложить их
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            try:
                # Извлекаем числа из строк времени
                prep_num = int(re.search(r'(\d+)', prep).group(1))
                cook_match = re.search(r'(\d+)(?:-(\d+))?', cook)
                
                if cook_match:
                    # Если есть диапазон в cook_time, берем максимум для total
                    cook_min = int(cook_match.group(1))
                    cook_max = int(cook_match.group(2)) if cook_match.group(2) else cook_min
                    
                    # Вычисляем диапазон общего времени
                    total_min = prep_num + cook_min
                    total_max = prep_num + cook_max
                    
                    if total_min == total_max:
                        return f"{total_min} minutes"
                    else:
                        return f"{total_min}-{total_max} minutes"
            except (AttributeError, ValueError):
                pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секции с заголовками типа "Lưu Ý", "Ghi Chú", "Biến Tấu", "Kết Luận"
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip()
            if any(keyword in heading_text for keyword in ['Lưu Ý', 'Ghi Chú', 'Biến Tấu', 'Kết Luận']):
                # Находим следующий параграф или ul
                next_elem = heading.find_next(['p', 'ul'])
                if next_elem:
                    if next_elem.name == 'p':
                        text = self.clean_text(next_elem.get_text())
                        # Берем первое предложение
                        if '.' in text:
                            text = text.split('.')[0] + '.'
                        if len(text) > 50:  # Проверяем, что это не пустой текст
                            return text
                    elif next_elem.name == 'ul':
                        items = next_elem.find_all('li')
                        if items:
                            text = self.clean_text(items[0].get_text())
                            # Берем первое предложение
                            if '.' in text:
                                text = text.split('.')[0] + '.'
                            if len(text) > 50:
                                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разделяем по запятой и очищаем
            tags = [self.clean_text(tag) for tag in keywords.split(',')]
            tags = [tag for tag in tags if tag and len(tag) > 2]
            return ', '.join(tags) if tags else None
        
        # Если нет keywords, создаем теги из названия блюда и категории
        tags = []
        
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем ключевые слова из названия
            words = dish_name.lower().split()
            stopwords = {'cách', 'nấu', 'làm', 'ngon', 'nhất', 'cho', 'tại', 'nhà', 'thơm', 'của', 'và', 'với'}
            
            # Берем осмысленные слова
            meaningful_words = []
            for word in words:
                if word not in stopwords and len(word) > 2:
                    meaningful_words.append(word)
            
            # Формируем теги из оставшихся слов
            if meaningful_words:
                # Объединяем слова, которые должны быть вместе (например "thịt bò")
                if len(meaningful_words) >= 2:
                    # Для составных названий
                    if meaningful_words[0] in ['cháo', 'món', 'canh', 'súp', 'lẩu']:
                        tags.append(meaningful_words[0])
                        if len(meaningful_words) > 1:
                            # Добавляем второе слово отдельно (например "thịt bò" -> "thịt", "bò")
                            combined = ' '.join(meaningful_words[1:3]) if len(meaningful_words) > 2 else meaningful_words[1]
                            tags.append(combined)
                            # Добавляем каждое слово отдельно
                            tags.extend(meaningful_words[1:min(3, len(meaningful_words))])
                    else:
                        # Для других случаев просто берем первые слова
                        tags.extend(meaningful_words[:4])
                else:
                    tags.extend(meaningful_words)
        
        # Добавляем общие теги
        if not any('món' in tag for tag in tags):
            tags.append('món ăn')
        
        # Проверяем наличие "chay" в названии
        if dish_name and 'chay' in dish_name.lower():
            tags.append('chay')
        
        # Добавляем "gia đình" если есть в оригинальном заголовке
        h1 = self.soup.find('h1')
        if h1 and 'gia đình' in h1.get_text().lower():
            tags.append('gia đình')
        
        # Удаляем дубликаты и ограничиваем до 5 тегов
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags[:5]) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                
                # Обрабатываем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    url = item['url']
                                    if url not in urls:
                                        urls.append(url)
                                elif 'contentUrl' in item:
                                    url = item['contentUrl']
                                    if url not in urls:
                                        urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ограничиваем до 3 изображений
        urls = urls[:3]
        
        return ','.join(urls) if urls else None
    
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
    """Обработка всех HTML файлов в директории preprocessed/venhaminh_vn"""
    import os
    
    # Путь относительно корня проекта
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "venhaminh_vn"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(VenhaMinhExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python venhaminh_vn.py")


if __name__ == "__main__":
    main()
