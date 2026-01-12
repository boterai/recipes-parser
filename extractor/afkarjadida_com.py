"""
Экстрактор данных рецептов для сайта afkarjadida.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AfkarjadidaExtractor(BaseRecipeExtractor):
    """Экстрактор для afkarjadida.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Из тега title убираем суффикс " - أفكار جديدة" и похожие фразы
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем название сайта и лишние слова
            text = re.sub(r'\s*-\s*أفكار جديدة\s*$', '', text)
            # Убираем фразы типа "تمنحك دفء" в конце названия
            text = re.sub(r'\s+(تمنحك|يمنحك|لك)\s+\w+\s*$', '', text)
            return self.clean_text(text)
        
        # Альтернативно из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = og_title['content']
            text = re.sub(r'\s*-\s*أفكار جديدة\s*$', '', text)
            text = re.sub(r'\s+(تمنحك|يمنحك|لك)\s+\w+\s*$', '', text)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем dish_name + короткое описание
        dish_name = self.extract_dish_name()
        
        if dish_name:
            # Проверяем есть ли в title дополнительная фраза после названия
            title = self.soup.find('title')
            if title:
                text = title.get_text()
                # Удаляем сайт
                text = re.sub(r'\s*-\s*أفكار جديدة\s*$', '', text)
                # Если в названии есть описательная часть после названия блюда
                # например "شوربة الفطر بالرافيولي تمنحك دفء"
                # Берём всё что после основного названия
                if dish_name in text:
                    # Находим позицию, где заканчивается название
                    idx = text.find(dish_name) + len(dish_name)
                    extra = text[idx:].strip()
                    if extra:
                        return f"{dish_name} {extra}."
            
            # Если нет дополнительного описания в title, возвращаем просто название + "."
            return f"{dish_name}."
        
        return None
    
    def parse_arabic_ingredient_text(self, text: str) -> List[Dict[str, any]]:
        """
        Парсинг текста с ингредиентами на арабском языке
        
        Пример входа: "2 كوب فطر مقطع و1 بصلة صغيرة مفرومة و2 فص ثوم"
        """
        ingredients = []
        
        # Разделяем по союзу "و" (и) и запятым
        parts = re.split(r'\s+و\s+|،\s*', text)
        
        for part in parts:
            part = self.clean_text(part)
            if not part or len(part) < 2:
                continue
            
            # Паттерн для извлечения: число + единица измерения + название
            # Примеры: "2 كوب فطر", "250 جм رافيولي", "1 بصلة صغيرة"
            
            # Основной паттерн: число (может быть дробным) + ед.измерения + название
            pattern = r'^(\d+(?:[.,/]\d+)?)\s+(كوب|أكواب|كيلو|جم|غرام|غم|ملعقة كبيرة|ملعقة صغيرة|ملاعق|فص|فصوص|قطعة|قطع|عدد|حبة|حبات|ملليلتر|لتر|رشة)\s+(.+)$'
            match = re.search(pattern, part)
            
            if match:
                amount_str, unit, name = match.groups()
                # Конвертируем дроби
                if '/' in amount_str:
                    nums = amount_str.split('/')
                    if len(nums) == 2:
                        try:
                            amount = float(nums[0]) / float(nums[1])
                        except:
                            amount = amount_str
                    else:
                        amount = amount_str
                else:
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except:
                        amount = amount_str
                
                ingredients.append({
                    "name": self.clean_text(name),
                    "units": self.clean_text(unit),
                    "amount": amount
                })
            else:
                # Попытка без единицы измерения: просто число + название
                pattern2 = r'^(\d+(?:[.,/]\d+)?)\s+(.+)$'
                match2 = re.search(pattern2, part)
                
                if match2:
                    amount_str, name = match2.groups()
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except:
                        amount = amount_str
                    
                    ingredients.append({
                        "name": self.clean_text(name),
                        "units": "عدد",  # По умолчанию "штуки"
                        "amount": amount
                    })
                else:
                    # Ингредиент без количества (например "ملح" или "فلفل أسود")
                    # Пропускаем слишком короткие или общие слова
                    if len(part) > 1 and part not in ['و', 'أو', 'مع']:
                        ingredients.append({
                            "name": self.clean_text(part),
                            "units": None,
                            "amount": None
                        })
        
        return ingredients
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из текста статьи"""
        ingredients = []
        
        # Ищем entry-content
        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            entry_content = self.soup.find('article')
        
        if not entry_content:
            return None
        
        # Ищем параграфы с ингредиентами
        paras = entry_content.find_all(['p', 'h2', 'h3', 'h4'])
        
        ingredients_section_found = False
        for i, para in enumerate(paras):
            text = para.get_text()
            
            # Проверяем, является ли это заголовком с ингредиентами
            if para.name in ['h2', 'h3', 'h4'] and ('المكونات' in text or 'المكوّنات' in text):
                ingredients_section_found = True
                # Берём следующий параграф
                if i + 1 < len(paras) and paras[i+1].name == 'p':
                    ing_text = paras[i+1].get_text()
                    
                    # Извлекаем текст после "وتتضمن المكوّنات" если есть
                    if 'وتتضمن' in ing_text and ('المكونات' in ing_text or 'المكوّنات' in ing_text):
                        # Найдём позицию после المكونات
                        idx1 = ing_text.find('المكونات')
                        idx2 = ing_text.find('المكوّنات')
                        idx = max(idx1, idx2)
                        if idx > 0:
                            ing_text = ing_text[idx:].replace('المكونات', '').replace('المكوّنات', '').strip()
                    else:
                        # Или извлекаем часть с числами (ингредиентами)
                        sentences = re.split(r'\.\s+', ing_text)
                        for sent in sentences:
                            if re.search(r'\d+\s+(كوب|ملعقة|فص|جم|غم)', sent):
                                ing_text = sent
                                break
                    
                    parsed = self.parse_arabic_ingredient_text(ing_text)
                    ingredients.extend(parsed)
                continue
            
            # Или если параграф сам содержит слово "المكوّنات" или "وتتضمن المكوّنات"
            if not ingredients_section_found and para.name == 'p':
                # Проверяем наличие маркеров ингредиентов
                if 'وتتضمن' in text and ('المكونات' in text or 'المكوّنات' in text):
                    # Найдём позицию после المكونات
                    idx1 = text.find('المكونات')
                    idx2 = text.find('المكوّنات')
                    idx = max(idx1, idx2)
                    if idx > 0:
                        ing_text = text[idx:].replace('المكونات', '').replace('المكوّنات', '').strip()
                        parsed = self.parse_arabic_ingredient_text(ing_text)
                        ingredients.extend(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем entry-content
        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            entry_content = self.soup.find('article')
        
        if not entry_content:
            return None
        
        # Ищем параграфы с инструкциями
        # Обычно они начинаются с глаголов действия или содержат слова "التحضير", "طريقة"
        paras = entry_content.find_all('p')
        
        for para in paras:
            text = self.clean_text(para.get_text())
            
            if not text or len(text) < 20:
                continue
            
            # Ищем параграфы с инструкциями (обычно содержат глаголы действия)
            # или начинаются со слов типа "يبدأ", "تسخّن", "تضاف"
            instruction_markers = [
                r'يبدأ\s+التحضير',
                r'تسخ[نّ]',
                r'تضاف',
                r'يضاف',
                r'يلي\s+ذلك',
                r'بعد\s+(ذلك|النضج)',
                r'في\s+الخطوة',
                r'خطوات\s+التحضير',
                r'طريقة\s+التحضير',
                r'التحضير.*كالتالي'
            ]
            
            is_instruction = any(re.search(pattern, text) for pattern in instruction_markers)
            
            if is_instruction:
                instructions.append(text)
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_times(self) -> tuple:
        """Извлечение времени приготовления из текста"""
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем в тексте статьи упоминания времени
        entry_content = self.soup.find(class_='entry-content')
        if entry_content:
            text = entry_content.get_text()
            
            # Паттерны для поиска времени
            # "20 دقيقة", "نصف ساعة", "ساعة ونصف"
            time_pattern = r'(\d+)\s*دقيقة|\d+\s*ساع[ةه]'
            
            # Ищем время приготовления
            cook_match = re.search(r'(وقت\s+الطهي|مدة\s+الطهي|يطهى?\s+لمدة)\s*[:：]?\s*(\d+)\s*(دقيقة|دقائق)', text)
            if cook_match:
                cook_time = f"{cook_match.group(2)} minutes"
            
            # Ищем время подготовки
            prep_match = re.search(r'(وقت\s+التحضير|مدة\s+التحضير|منقوع\s+لمدة)\s*[:：]?\s*(\d+)\s*(دقيقة|دقائق)', text)
            if prep_match:
                prep_time = f"{prep_match.group(2)} minutes"
            
            # Ищем общее время
            total_match = re.search(r'(الوقت\s+الإجمالي|المدة\s+الكاملة)\s*[:：]?\s*(\d+)\s*(دقيقة|دقائق)', text)
            if total_match:
                total_time = f"{total_match.group(2)} minutes"
            
            # Если не нашли явных меток, ищем просто числа с "دقيقة"
            # и пытаемся определить по контексту
            if not cook_time and not prep_time:
                # Поиск всех упоминаний времени
                time_mentions = re.findall(r'(\d+)[-–]\s*(\d+)\s*دقيقة|(\d+)\s*دقيقة', text)
                if time_mentions:
                    for match in time_mentions:
                        if match[0] and match[1]:  # Диапазон времени (6-8 дقيقة)
                            if not cook_time:
                                cook_time = f"{match[1]} minutes"
                        elif match[2]:  # Одно число
                            if not cook_time:
                                cook_time = f"{match[2]} minutes"
        
        return prep_time, cook_time, total_time
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из breadcrumbs"""
        # Ищем в JSON-LD breadcrumbs
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                if not script.string:
                    continue
                
                data = json.loads(script.string)
                
                # Ищем BreadcrumbList в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            elements = item.get('itemListElement', [])
                            # Берём предпоследний элемент (последний - это сам рецепт)
                            if len(elements) >= 2:
                                category = elements[-2].get('name')
                                if category and category != 'الرئيسية':
                                    return self.clean_text(category)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (если есть)"""
        # На afkarjadida.com теги могут быть в meta или в тексте
        # Пока возвращаем None, так как в примерах их нет или они не всегда есть
        
        # Можно попробовать извлечь из keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Чистим и возвращаем
            keywords = self.clean_text(keywords)
            if keywords:
                return keywords
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url:
                urls.append(url)
        
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            url = item.get('url') or item.get('contentUrl')
                            if url and url not in urls:
                                urls.append(url)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Возвращаем как строку через запятую (без пробелов)
        if urls:
            return ','.join(urls)
        
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
        prep_time, cook_time, total_time = self.extract_times()
        category = self.extract_category()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": None,  # На afkarjadida.com обычно нет nutrition info
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": None,  # Заметок обычно нет
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """
    Точка входа для обработки HTML-файлов afkarjadida.com
    """
    import os
    
    # Ищем директорию с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "afkarjadida_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(AfkarjadidaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/afkarjadida_com.py")


if __name__ == "__main__":
    main()
