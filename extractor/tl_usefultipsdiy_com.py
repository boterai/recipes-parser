"""
Экстрактор данных рецептов для сайта tl.usefultipsdiy.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TlUsefulTipsDiyExtractor(BaseRecipeExtractor):
    """Экстрактор для tl.usefultipsdiy.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 и извлекаем ключевое название блюда
        h1 = self.soup.find('h1')
        if h1:
            h1_text = self.clean_text(h1.get_text())
            
            # Сначала пытаемся найти по ключевым паттернам (более специфичные)
            # Например, "Lugaw ng Semolina", "Pancake ng Kalabasa", "Poached Egg"
            patterns = [
                r'(Lugaw\s+[Nn]g\s+\S+)',
                r'(Pancake\s+[Nn]g\s+\S+)',
                r'(Mga\s+Pancake\s+[Nn]g\s+\S+)',
                r'(\S+\s+Pancakes?)',
                r'(Poached\s+\w+)',
                r'(\w+\s+Egg)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, h1_text, re.I)
                if match:
                    name = match.group(1)
                    # Capitalize properly
                    return name.title() if name else name
            
            # Если паттерны не помогли, пытаемся извлечь название блюда из длинного заголовка
            # Ищем паттерн с двоеточием (обычно название до двоеточия)
            if ':' in h1_text:
                parts = h1_text.split(':')
                # Берем часть до двоеточия
                first_part = parts[0]
                
                # Ищем ключевые фразы, которые могут быть названием блюда
                # Обычно после "Lutuin Ang" или "Magluto ng" идет название
                name_patterns = [
                    r'Lutuin\s+Ang\s+(.+?)(?:\s+Sa|\s+Ng|$)',
                    r'Magluto\s+ng\s+(.+?)(?:\s+Sa|\s+Ng|$)',
                    r'Ang\s+(.+?)(?:\s+Sa|\s+Ng|\s+:)',
                ]
                
                for np in name_patterns:
                    match = re.search(np, first_part, re.I)
                    if match:
                        name = match.group(1).strip()
                        # Очищаем от лишних слов
                        name = re.sub(r'\s+(Sa|Ng|At)\s*$', '', name, flags=re.I)
                        if len(name) > 5:
                            return name
            
            # Если все не помогло, возвращаем весь h1 (последний вариант)
            return h1_text
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов
        Возвращает JSON-строку со списком ингредиентов
        Формат: [{"name": "...", "units": "...", "amount": ...}, ...]
        """
        ingredients = []
        
        # Ищем UL, который содержит ингредиенты
        # Обычно это список, где есть несколько элементов с числами и единицами
        all_uls = self.soup.find_all('ul')
        
        best_ul = None
        max_ingredients = 0
        
        for ul in all_uls:
            temp_ingredients = []
            direct_lis = ul.find_all('li', recursive=False)
            
            for li in direct_lis:
                text = self.clean_text(li.get_text())
                
                # Ищем паттерн: число + единица + название
                # Примеры: "500 ML ng gatas", "50 g semolina", "1.5 tsp baking powder"
                pattern = r'^(\d+(?:\.\d+)?(?:-\d+)?)\s*(g|ml|mL|ML|tsp|tbsp|tablespoon|tablespoons|teaspoon|teaspoons|cup|cups|piece|pieces|kg)\s+(.+?)(?:;|\.)?$'
                match = re.match(pattern, text, re.I)
                
                if match:
                    amount_str, unit, name = match.groups()
                    temp_ingredients.append((amount_str, unit, name))
                else:
                    # Специальный случай для "asin - halos isang-katlo ng isang kutsarita"
                    # Ищем название без количества в начале, но с указанием на количество
                    alt_pattern = r'^(\w+(?:\s+\w+)?)\s*-\s*.*(kutsarita|teaspoon|tablespoon|cup|gram)'
                    alt_match = re.match(alt_pattern, text, re.I)
                    if alt_match and len(temp_ingredients) > 0:
                        # Это похоже на ингредиент (salt, etc.)
                        name = alt_match.group(1)
                        # Извлекаем количество из описания
                        if 'katlo' in text or 'third' in text.lower():
                            temp_ingredients.append(('0.33', 'teaspoon', name))
                        elif 'kalahati' in text or 'half' in text.lower():
                            temp_ingredients.append(('0.5', 'teaspoon', name))
            
            # Выбираем UL с наибольшим количеством ингредиентов (но не слишком много)
            if 3 <= len(temp_ingredients) <= 15 and len(temp_ingredients) > max_ingredients:
                best_ul = ul
                max_ingredients = len(temp_ingredients)
                ingredients = temp_ingredients
        
        # Преобразуем в нужный формат
        result = []
        for amount_str, unit, name in ingredients:
            # Конвертируем amount в число (int или float)
            try:
                # Обработка диапазонов (20-25 -> берем среднее или первое)
                if '-' in amount_str:
                    parts = amount_str.split('-')
                    amount = float(parts[0])  # Берем первое значение
                else:
                    amount = float(amount_str)
                if amount == int(amount):
                    amount = int(amount)
            except:
                amount = amount_str
            
            # Очищаем название от артиклей и предлогов
            name = re.sub(r'^(ng|na|sa|ang)\s+', '', name, flags=re.I)
            name = re.sub(r',.*$', '', name)  # Удаляем все после запятой
            name = name.strip()
            
            # Нормализуем единицы (ML -> mL)
            if unit.upper() == 'ML':
                unit = 'mL'
            
            if name and len(name) > 1:
                result.append({
                    "name": name,
                    "units": unit,
                    "amount": amount
                })
        
        return json.dumps(result, ensure_ascii=False) if result else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем упорядоченные списки (ol)
        ordered_lists = self.soup.find_all('ol')
        
        # Ищем OL, который содержит инструкции по приготовлению
        best_ol = None
        max_score = 0
        
        for ol in ordered_lists:
            items = ol.find_all('li', recursive=False)
            
            # Проверяем, что это действительно инструкции
            if len(items) < 3:  # Слишком мало шагов
                continue
            
            # Оцениваем по ключевым словам (кулинарные термины)
            text = ol.get_text().lower()
            score = 0
            cooking_terms = ['ibuhos', 'kumulo', 'hinalo', 'lutuin', 'magdagdag', 'takpan', 
                           'alisin', 'ihain', 'cook', 'mix', 'add', 'remove', 'pour', 'hintay']
            for term in cooking_terms:
                score += text.count(term)
            
            if score > max_score:
                max_score = score
                best_ol = ol
        
        if not best_ol:
            # Если не нашли по score, берем первый OL с >= 4 шагами
            for ol in ordered_lists:
                items = ol.find_all('li', recursive=False)
                if len(items) >= 4:
                    best_ol = ol
                    break
        
        if best_ol:
            items = best_ol.find_all('li', recursive=False)
            
            for idx, item in enumerate(items, 1):
                full_text = item.get_text()
                
                # Разбиваем по двойным переносам строк (обычно отделяют инструкцию от описания изображения)
                parts = re.split(r'\n\s*\n', full_text)
                
                # Первая часть - основная инструкция
                if parts:
                    main_instruction = self.clean_text(parts[0])
                    main_instruction = main_instruction.rstrip('.') + '.'
                    steps.append(f"{idx}. {main_instruction}")
                    
                    # Проверяем остальные части на наличие дополнительных инструкций
                    # Ищем строки начинающиеся с кулинарных глаголов
                    if len(parts) > 1:
                        for part in parts[1:]:
                            part_clean = self.clean_text(part)
                            # Ищем предложения внутри части
                            sentences = re.split(r'\.\s+', part_clean)
                            for sentence in sentences:
                                sentence = sentence.strip()
                                # Проверяем, начинается ли с кулинарного глагола
                                cooking_verbs = ['hayaang', 'ihain', 'ilagay', 'idagdag', 'alisin', 
                                               'ulitin', 'isawsaw', 'gupitin', 'ibuhos']
                                if any(sentence.lower().startswith(verb) for verb in cooking_verbs):
                                    # Это дополнительная инструкция
                                    if len(sentence) > 20:  # Достаточно длинная
                                        additional_step = sentence.rstrip('.') + '.'
                                        steps.append(f"{len(steps) + 1}. {additional_step}")
                                        # Берем только первую найденную доп. инструкцию
                                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Для tl.usefultipsdiy.com категория обычно определяется по содержанию
        # Проверяем ключевые слова в тексте
        text = self.soup.get_text().lower()
        
        # Простая эвристика на основе ключевых слов
        if any(word in text for word in ['breakfast', 'agahan', 'morning']):
            return 'Breakfast'
        elif any(word in text for word in ['dessert', 'sweet', 'matamis', 'cake', 'pancake']):
            return 'Dessert'
        elif any(word in text for word in ['dinner', 'hapunan', 'lunch']):
            return 'Main Course'
        
        # По умолчанию возвращаем None
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем паттерны времени в тексте
        text = self.soup.get_text()
        
        # Поиск явных упоминаний prep time не работает для этого сайта
        # Используем эвристику: prep time обычно 5-15 минут
        # Ищем все упоминания минут в разумном диапазоне
        time_matches = re.findall(r'(\d+)\s*minut', text, re.I)
        
        if time_matches:
            # Фильтруем значения в диапазоне prep time (5-20 минут)
            prep_times = [int(t) for t in time_matches if 5 <= int(t) <= 20]
            if prep_times:
                # Берем наиболее встречающееся или среднее
                prep = max(set(prep_times), key=prep_times.count)
                return f"{prep} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем паттерны времени в тексте
        text = self.soup.get_text()
        
        # Cook time обычно меньше (2-10 минут для простых рецептов)
        time_matches = re.findall(r'(\d+)(?:-(\d+))?\s*minut', text, re.I)
        
        if time_matches:
            # Ищем упоминания коротких интервалов (обычно cook time)
            cook_times = []
            for match in time_matches:
                if match[1]:  # Диапазон (например, "3-5")
                    start, end = int(match[0]), int(match[1])
                    if 2 <= start <= 10:
                        cook_times.append(start)
                else:
                    t = int(match[0])
                    if 2 <= t <= 10:
                        cook_times.append(t)
            
            if cook_times:
                # Берем наименьшее значение (обычно это actual cook time)
                cook = min(cook_times)
                return f"{cook} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Суммируем prep_time и cook_time если они есть
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            if prep_match and cook_match:
                prep_mins = int(prep_match.group(1))
                cook_mins = int(cook_match.group(1))
                total = prep_mins + cook_mins
                return f"{total} minutes"
        elif prep:
            # Если есть только prep, используем как приблизительное total
            return prep
        elif cook:
            return cook
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # Ищем в тексте упоминания о подаче (serving suggestions)
        text = self.soup.get_text()
        
        # Ищем паттерны типа "Maaari itong ihain..." (Can be served with...)
        patterns = [
            r'(Maaari\s+itong\s+ihain.*?\.)',
            r'(Ihain\s+ang.*?\.)',
            r'(Serve\s+(?:with|the).*?\.)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.DOTALL)
            if match:
                note = self.clean_text(match.group(1))
                # Очищаем от лишних пробелов
                note = re.sub(r'\s+', ' ', note)
                # Проверяем длину (разумная заметка)
                if 20 < len(note) < 300:
                    return note
        
        # Если не нашли serving suggestions, ищем другие полезные заметки
        # Например, в последних параграфах или после инструкций
        all_ols = self.soup.find_all('ol')
        if all_ols:
            # Текст после последнего OL может содержать заметки
            last_ol = all_ols[-1]
            # Ищем следующие параграфы
            next_p = last_ol.find_next('p')
            if next_p:
                note_text = self.clean_text(next_p.get_text())
                if 20 < len(note_text) < 300 and any(word in note_text.lower() for word in ['ihain', 'serve', 'may', 'with']):
                    return note_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов
        Возвращает строку с тегами через запятую
        """
        tags = []
        
        # Ищем в meta keywords
        keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            tags_str = keywords_meta['content']
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        # Если не нашли, пытаемся извлечь из JSON-LD
        if not tags:
            json_ld = self.soup.find('script', type='application/ld+json')
            if json_ld:
                try:
                    data = json.loads(json_ld.string)
                    if 'keywords' in data and data['keywords']:
                        tags_str = data['keywords']
                        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
                except:
                    pass
        
        # Если все еще нет тегов, создаем на основе dish_name и category
        if not tags:
            dish_name = self.extract_dish_name()
            category = self.extract_category()
            
            if dish_name:
                # Извлекаем ключевые слова из названия
                words = re.findall(r'\b\w+\b', dish_name.lower())
                # Фильтруем служебные слова
                stopwords = {'ang', 'ng', 'sa', 'na', 'at', 'kung', 'para', 'mga', 'may'}
                tags = [w for w in words if w not in stopwords and len(w) > 3][:4]
            
            if category:
                tags.append(category.lower())
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений
        Возвращает строку с URL через запятую
        """
        urls = []
        
        # Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем в JSON-LD
        json_ld = self.soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        url = img['url']
                        if url not in urls:
                            urls.append(url)
                    elif isinstance(img, str):
                        if img not in urls:
                            urls.append(img)
            except:
                pass
        
        # Ищем основное изображение на странице
        # (обычно первое большое изображение)
        main_content = self.soup.find('div', class_='post-content')
        if main_content:
            images = main_content.find_all('img', src=True)[:3]
            for img in images:
                src = img.get('src')
                if src and 'http' in src and src not in urls:
                    urls.append(src)
        
        # Возвращаем как строку через запятую (без пробелов)
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Основная функция для обработки директории с HTML файлами"""
    import os
    
    # Путь к директории с preprocessed HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "tl_usefultipsdiy_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(TlUsefulTipsDiyExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python tl_usefultipsdiy_com.py")


if __name__ == "__main__":
    main()
