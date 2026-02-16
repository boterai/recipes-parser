"""
Экстрактор данных рецептов для сайта clydescares.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ClydescaresExtractor(BaseRecipeExtractor):
    """Экстрактор для clydescares.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h3 с классом gb-headline
        h3 = self.soup.find('h3', class_=lambda x: x and 'gb-headline' in x)
        if h3:
            text = h3.get_text()
            # Убираем всё после символа | (включая сам символ)
            text = re.split(r'\s*[|｜]\s*', text)[0]
            text = self.clean_text(text)
            
            # Убираем лишние слова в начале и конце
            # Список шаблонов для удаления
            remove_patterns = [
                # В конце
                r'\s+맛있게\s+끓이는\s+법.*$',
                r'\s+완벽\s+레시피.*$',
                r'\s+법과\s+재료\s+소개.*$',
                r'의\s+맛있는\s+조합.*$',
                r'\s+완벽한\s+레시피.*$',
                # В начале
                r'^싱싱한\s+닭날개로\s+만드는\s+',
                r'^.*로\s+만드는\s+',
            ]
            
            for pattern in remove_patterns:
                text = re.sub(pattern, '', text)
            
            return self.clean_text(text)
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем всё после символа | и - clydescares
            text = re.split(r'\s*[|｜]\s*', text)[0]
            text = re.sub(r'\s*-\s*clydescares.*$', '', text, flags=re.IGNORECASE)
            
            # Убираем лишние слова
            for pattern in [r'\s+맛있게\s+끓이는\s+법.*$', r'\s+완벽\s+레시피.*$', r'의\s+맛있는\s+조합.*$', r'^.*로\s+만드는\s+']:
                text = re.sub(pattern, '', text)
            
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в параграфах описание, которое обычно идет в начале
        paragraphs = self.soup.find_all('p')
        
        # Ищем параграф, который содержит описательный текст о блюде
        # Обычно это второй или третий параграф, содержащий полное описание
        for p in paragraphs[:10]:
            text = p.get_text().strip()
            # Пропускаем короткие параграфы
            if len(text) < 30:
                continue
            # Пропускаем параграфы с номерами шагов
            if re.match(r'^\d+\.', text):
                continue
            # Пропускаем параграфы со списком ингредиентов
            if '재료는' in text or '필요한 재료' in text:
                continue
            # Пропускаем параграфы с рекламными ссылками
            if '✅' in text or 'http' in text.lower():
                continue
            # Берем параграф, который содержит описательное предложение
            if len(text) > 50 and ('는' in text or '입니다' in text or '합니다' in text):
                return self.clean_text(text)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем параграф с упоминанием ингредиентов
        paragraphs = self.soup.find_all('p')
        ingredients_text = None
        
        for p in paragraphs:
            text = p.get_text().strip()
            # Ищем параграф с "필요한 재료는" или "재료는"
            if '재료는' in text or '필요한 재료' in text:
                ingredients_text = text
                break
        
        if ingredients_text:
            # Парсим ингредиенты из текста
            # Пример: "오징어 1마리, 무 200g, 대파 1대, 마늘 2~3쪽, 고춧가루 1큰술, 국간장 2큰술, 물 5컵"
            # Извлекаем часть после "재료는" или после двоеточия
            if ':' in ingredients_text:
                ingredients_text = ingredients_text.split(':', 1)[1]
            elif '재료는' in ingredients_text:
                ingredients_text = ingredients_text.split('재료는', 1)[1]
            
            # Разделяем по запятым
            items = [item.strip() for item in ingredients_text.split(',')]
            
            for item in items:
                if not item or len(item) < 2:
                    continue
                
                # Убираем точку в конце
                item = item.rstrip('.')
                
                parsed = self.parse_ingredient(item)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли в параграфе, ищем в других местах
        if not ingredients:
            # Попробуем найти списки ul/li
            lists = self.soup.find_all(['ul', 'ol'])
            for lst in lists:
                items = lst.find_all('li')
                for item in items:
                    text = item.get_text().strip()
                    if text and len(text) > 2:
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для корейских рецептов
        
        Args:
            ingredient_text: Строка вида "오징어 1마리" или "무 200g"
            
        Returns:
            dict: {"name": "오징어", "units": "마리", "amount": "1"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для корейских ингредиентов
        # Формат: [название] [количество][единица]
        # Примеры: "오징어 1마리", "무 200g", "대파 1대", "마늘 2~3쪽"
        
        # Сначала пробуем найти количество с единицами измерения
        # Корейские единицы: 마리, 대, 쪽, 큰술, 컵, g, kg, ml, l и т.д.
        pattern = r'^(.+?)\s+([\d~\-\.]+)\s*(마리|대|쪽|큰술|작은술|컵|그램|킬로그램|밀리리터|리터|g|kg|ml|l|개|장|숟가락|티스푼|테이블스푼|tbsp|tsp)?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            name, amount, units = match.groups()
            # Возвращаем в правильном порядке: name, units, amount (как в reference)
            return {
                "name": name.strip(),
                "units": units.strip() if units else None,
                "amount": amount.strip()
            }
        
        # Если не совпало, пробуем без единиц (только название и количество)
        pattern2 = r'^(.+?)\s+([\d~\-\.]+)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            name, amount = match2.groups()
            return {
                "name": name.strip(),
                "units": None,
                "amount": amount.strip()
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем в параграфах шаги приготовления
        paragraphs = self.soup.find_all('p')
        
        # Сначала ищем параграфы с явной нумерацией (1. 2. 3. и т.д.)
        numbered_steps = []
        for p in paragraphs:
            text = p.get_text().strip()
            
            # Пропускаем короткие параграфы
            if len(text) < 20:
                continue
            
            # Ищем параграфы с номерами шагов в начале
            # Формат может быть: "1. текст", "2. текст" и т.д.
            match = re.match(r'^(\d+)\.\s+(.+)', text)
            if match:
                num, step_text = match.groups()
                numbered_steps.append((int(num), step_text))
        
        # Если нашли numbered steps, используем их
        if numbered_steps:
            # Сортируем по номеру и собираем
            numbered_steps.sort(key=lambda x: x[0])
            for num, step_text in numbered_steps:
                steps.append(f"{num}. {step_text}")
        
        # Если не нашли numbered steps, ищем параграфы с инструкциями
        if not steps:
            # Ищем параграфы, которые начинаются с "먼저", "그 후", "다음" и т.д.
            instruction_markers = ['먼저', '그 후', '다음', '마지막으로']
            instruction_paragraphs = []
            
            for p in paragraphs:
                text = p.get_text().strip()
                
                # Пропускаем короткие и длинные параграфы
                if len(text) < 30 or len(text) > 500:
                    continue
                
                # Проверяем, начинается ли с маркера инструкции
                if any(text.startswith(marker) for marker in instruction_markers):
                    instruction_paragraphs.append(text)
                # Или содержит глаголы приготовления
                elif any(verb in text for verb in ['섞어', '올려', '뿌려', '넣고', '끓여', '익으면', '준비합니다']):
                    # Проверяем, что это не просто описание, а инструкция
                    if '합니다' in text or '줍니다' in text or '세요' in text or '됩니다' in text:
                        # Проверяем, что это похоже на инструкцию (короткий параграф с действиями)
                        if 50 < len(text) < 300:
                            instruction_paragraphs.append(text)
            
            # Если нашли параграфы с инструкциями, нумеруем их
            if instruction_paragraphs:
                for i, text in enumerate(instruction_paragraphs, 1):
                    steps.append(f"{i}. {text}")
            else:
                # Последняя попытка - ищем один параграф, который содержит всю инструкцию
                # (с фразами "먼저", "그 후" внутри текста)
                for p in paragraphs:
                    text = p.get_text().strip()
                    if '먼저' in text and '그 후' in text:
                        if 100 < len(text) < 500:
                            # Это один параграф с несколькими шагами
                            # Разбиваем по маркерам
                            parts = []
                            for marker in ['먼저, ', '그 후, ', '다음, ', '마지막으로, ']:
                                if marker in text:
                                    text = text.replace(marker, f'|||{marker}')
                            
                            parts = [part.strip() for part in text.split('|||') if part.strip()]
                            if len(parts) > 1:
                                for i, part in enumerate(parts, 1):
                                    steps.append(f"{i}. {part}")
                                break
        
        # Объединяем шаги
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в span с классом post-term-item
        terms = self.soup.find_all('span', class_='post-term-item')
        
        if terms:
            categories = []
            for term in terms:
                link = term.find('a')
                if link:
                    cat = link.get_text().strip()
                    if cat:
                        categories.append(cat)
            
            if categories:
                # Для совместимости с форматом, возвращаем "Main Course"
                # Можно также вернуть первую найденную категорию
                return "Main Course"
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        paragraphs = self.soup.find_all('p')
        
        time_patterns = {
            'prep': ['준비.*시간', '손질.*시간', '마리네이드.*시간', '재워', 'prep.*time', '마리네이드'],
            'cook': ['조리.*시간', '익히는.*시간', '끓이는.*시간', '소요', 'cook.*time', r'약\s+\d+[-~]\d+분.*조리'],
            'total': ['총.*시간', '전체.*시간', '이내', 'total.*time', '10분.*만들']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        # Для каждого параграфа проверяем паттерны
        for p in paragraphs:
            p_text = p.get_text()
            
            # Проверяем паттерны для типа времени
            for pattern in patterns:
                if re.search(pattern, p_text, re.IGNORECASE):
                    # Ищем время в минутах
                    # Примеры: "약 30분", "20-25분", "30분에서 1시간", "10분 이내"
                    time_match = re.search(r'(\d+(?:[-~]\d+)?)\s*분', p_text)
                    if time_match:
                        minutes = time_match.group(1)
                        return f"{minutes} minutes"
                    
                    time_match = re.search(r'(\d+(?:[-~]\d+)?)\s*minutes?', p_text, re.IGNORECASE)
                    if time_match:
                        minutes = time_match.group(1)
                        return f"{minutes} minutes"
        
        # Если не нашли по паттернам, для prep_time ищем упоминания маринования
        if time_type == 'prep':
            for p in paragraphs:
                p_text = p.get_text()
                # "30분에서 1시간 정도 재워"
                if '재워' in p_text or '마리네이드' in p_text:
                    time_match = re.search(r'(\d+)\s*분(?:에서|\s*[-~]\s*)', p_text)
                    if time_match:
                        minutes = time_match.group(1)
                        return f"{minutes} minutes"
        
        # Для cook_time ищем более общие упоминания времени приготовления
        if time_type == 'cook':
            for p in paragraphs:
                p_text = p.get_text()
                # "20-25분간 조리", "200도에서 20-25분"
                if '조리' in p_text or '익' in p_text or '끓' in p_text:
                    time_match = re.search(r'(\d+(?:[-~]\d+)?)\s*분', p_text)
                    if time_match:
                        minutes = time_match.group(1)
                        return f"{minutes} minutes"
        
        # Для total_time ищем фразы типа "10분 이내"
        if time_type == 'total':
            for p in paragraphs:
                p_text = p.get_text()
                # "10분 이내에 손쉽게"
                if '이내' in p_text or '만들' in p_text:
                    time_match = re.search(r'(\d+)\s*분', p_text)
                    if time_match:
                        minutes = time_match.group(1)
                        return f"{minutes} minutes"
        
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
        """Извлечение заметок и советов"""
        # Ищем в параграфах заметки и советы
        # Обычно содержат ключевые слова типа "팁", "주의", "중요", "추천"
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text().strip()
            
            # Ищем параграфы с советами
            if any(keyword in text for keyword in ['팁', '주의', '중요', '추천', '조절', '포인트']):
                # Пропускаем слишком длинные параграфы (это скорее всего не заметка)
                if 30 < len(text) < 200:
                    return self.clean_text(text)
        
        # Также проверяем последние параграфы (часто советы в конце)
        for p in reversed(paragraphs[-5:]):
            text = p.get_text().strip()
            if 30 < len(text) < 200:
                # Пропускаем рекламные ссылки
                if '✅' not in text and 'http' not in text.lower():
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в разных местах
        
        # 1. Из заголовка H3 (после символа |)
        h3 = self.soup.find('h3', class_=lambda x: x and 'gb-headline' in x)
        if h3:
            h3_text = h3.get_text()
            # Берем часть после | до конца
            parts = re.split(r'\s*[|｜]\s*', h3_text)
            if len(parts) > 1:
                # Последняя часть может содержать теги через запятую
                last_part = parts[-1]
                # Разделяем по запятым
                potential_tags = [tag.strip() for tag in last_part.split(',')]
                tags.extend(potential_tags)
        
        # 2. Из категорий (post-term-item)
        terms = self.soup.find_all('span', class_='post-term-item')
        for term in terms:
            link = term.find('a')
            if link:
                tag = link.get_text().strip()
                if tag and tag not in tags:
                    tags.append(tag)
        
        # 3. Из title тега (после |)
        if not tags:
            title = self.soup.find('title')
            if title:
                title_text = title.get_text()
                parts = re.split(r'\s*[|｜]\s*', title_text)
                if len(parts) > 1:
                    # Берем часть между первым и последним |
                    for i in range(1, len(parts) - 1):
                        potential_tags = [tag.strip() for tag in parts[i].split(',')]
                        tags.extend(potential_tags)
        
        if tags:
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_clean = tag.strip()
                if tag_clean and tag_clean not in seen and len(tag_clean) > 1:
                    seen.add(tag_clean)
                    unique_tags.append(tag_clean)
            
            # Возвращаем через запятую с пробелом
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в figure с классом gb-block-image
        figures = self.soup.find_all('figure', class_=lambda x: x and 'gb-block-image' in x)
        
        for figure in figures:
            img = figure.find('img')
            if img:
                # Берем src
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
                
                # Также пробуем взять из srcset (берем самое большое изображение)
                srcset = img.get('srcset')
                if srcset and not src:
                    # Парсим srcset
                    # Формат: "url1 400w, url2 300w, url3 150w"
                    parts = srcset.split(',')
                    if parts:
                        # Берем первое (обычно самое большое)
                        first_url = parts[0].strip().split()[0]
                        if first_url and first_url not in urls:
                            urls.append(first_url)
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url not in urls:
                urls.append(url)
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url and url not in urls:
                urls.append(url)
        
        # Возвращаем первые 3 изображения через запятую без пробелов
        if urls:
            return ','.join(urls[:3])
        
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
    """Обработка HTML файлов из директории preprocessed/clydescares_com"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "clydescares_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ClydescaresExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python clydescares_com.py")


if __name__ == "__main__":
    main()
