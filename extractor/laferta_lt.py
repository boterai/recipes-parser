"""
Экстрактор данных рецептов для сайта laferta.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LafertaExtractor(BaseRecipeExtractor):
    """Экстрактор для laferta.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            dish_name = h1.get_text(strip=True)
            # Убираем слово "receptas" из названия и его вариации
            dish_name = re.sub(r'\s+receptas?\s*$', '', dish_name, flags=re.IGNORECASE)
            # Для названий в родительном падеже (Velykinio pyrago) - оставляем как есть
            # Но удаляем "receptas" если есть
            return self.clean_text(dish_name)
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            headline = item['headline']
                            headline = re.sub(r'\s+receptas?\s*$', '', headline, flags=re.IGNORECASE)
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        article = self.soup.find('article')
        if article:
            # Берем первый параграф в статье
            first_p = article.find('p')
            if first_p:
                full_text = first_p.get_text(strip=True)
                # Извлекаем только первое предложение (до первой точки)
                first_sentence = full_text.split('.')[0] + '.'
                return self.clean_text(first_sentence)
        
        return None
    
    def extract_meta_info(self) -> dict:
        """Извлечение метаинформации (время, порции, сложность)"""
        meta = {
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'servings': None,
            'difficulty': None
        }
        
        article = self.soup.find('article')
        if not article:
            return meta
        
        # Ищем первый список ul в статье
        first_ul = article.find('ul')
        if first_ul:
            items = first_ul.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                
                # Извлекаем время
                if 'laikas' in text.lower():
                    # Варианты:
                    # "Laikas:40 minučių" -> "40 minutes"
                    # "Laikas:1,5 valandos" -> "90 minutes"
                    # "Laikas:1 valanda 30 minučių" -> "1 hour 30 minutes"
                    
                    # Попытка 1: часы и минуты
                    hour_min_match = re.search(r'(\d+)\s*valand[aąo][s]?\s*(\d+)\s*minuč', text, re.IGNORECASE)
                    if hour_min_match:
                        hours = hour_min_match.group(1)
                        minutes = hour_min_match.group(2)
                        meta['cook_time'] = f"{hours} hour {minutes} minutes"
                        meta['total_time'] = f"{hours} hour {minutes} minutes"
                        continue
                    
                    # Попытка 2: только часы с десятичной дробью (1,5 valandos)
                    hour_decimal_match = re.search(r'(\d+)[,.](\d+)\s*valand', text, re.IGNORECASE)
                    if hour_decimal_match:
                        hours_str = hour_decimal_match.group(1)
                        decimal_str = hour_decimal_match.group(2)
                        # Преобразуем в десятичное число и затем в минуты
                        total_hours = float(f"{hours_str}.{decimal_str}")
                        total_minutes = int(total_hours * 60)
                        meta['cook_time'] = f"{total_minutes} minutes"
                        meta['total_time'] = f"{total_minutes} minutes"
                        continue
                    
                    # Попытка 3: только минуты
                    min_match = re.search(r'(\d+)\s*minuč', text, re.IGNORECASE)
                    if min_match:
                        minutes = min_match.group(1)
                        meta['cook_time'] = f"{minutes} minutes"
                        meta['total_time'] = f"{minutes} minutes"
                        continue
                
                # Извлекаем порции
                elif 'porcijos' in text.lower():
                    # Пример: "Porcijos:4"
                    servings_match = re.search(r'(\d+)', text)
                    if servings_match:
                        meta['servings'] = servings_match.group(1)
                
                # Извлекаем сложность
                elif 'difficultas' in text.lower() or 'dificultas' in text.lower():
                    # Пример: "Difficultas:Vidutinio sudėtingumo"
                    difficulty_match = re.search(r'diff?icultas\s*:\s*(.+)', text, re.IGNORECASE)
                    if difficulty_match:
                        meta['difficulty'] = difficulty_match.group(1).strip()
        
        return meta
    
    def parse_ingredient_item(self, text: str) -> list:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "300 g šviežių grybų (pvz., pievagrybių)"
            
        Returns:
            list of dict: [{"name": "šviežių grybų", "amount": 300, "units": "g"}]
        """
        if not text:
            return []
        
        text = self.clean_text(text)
        
        # Специальная обработка для "Druska ir pipirai pagal skonį"
        if 'druska' in text.lower() and 'pipirai' in text.lower():
            # Разделяем на два ингредиента
            return [
                {"name": "druskos", "units": None, "amount": None},
                {"name": "pipirų", "units": None, "amount": None}
            ]
        
        # Паттерн для извлечения: количество, единица, название
        # Примеры:
        # "300 g šviežių grybų (pvz., pievagrybių)"
        # "1 vidutinio dydžio svogūno"
        # "2 vidutinio dydžio morkų"
        # "1 litras daržovių sultinio"
        
        # Попытка 1: число + единица + название
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s+(g|kg|ml|l|litras|litrų|vnt\.|pcs|pakelis|šaukštelis|skiltelės)\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, units, name = match.groups()
            # Очистка названия от скобок с примерами и от "pagal skonį"
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\s*\(.*?\)\s*', '', name)
            name = re.sub(r'\s*pagal\s+skonį\s*', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*\(patiekimui\)\s*', '', name, flags=re.IGNORECASE)
            name = self.clean_text(name).lower()
            
            # Преобразуем amount в int если это целое число
            try:
                amount = int(amount_str) if '.' not in amount_str and ',' not in amount_str else float(amount_str.replace(',', '.'))
            except:
                amount = amount_str
            
            return [{
                "name": name,
                "units": units,
                "amount": amount
            }]
        
        # Попытка 2: число + описательная единица (как "vidutinio dydžio")
        pattern2 = r'^(\d+)\s+(vidutinio\s+dydžio|maž[ao]s?|didel[ėę]s?)\s+(.+)$'
        match = re.match(pattern2, text, re.IGNORECASE)
        
        if match:
            amount_str, size_desc, name = match.groups()
            name = self.clean_text(name).lower()
            
            try:
                amount = int(amount_str)
            except:
                amount = amount_str
            
            return [{
                "name": name,
                "units": size_desc,
                "amount": amount
            }]
        
        # Попытка 3: только число + название (без единицы)
        pattern3 = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match = re.match(pattern3, text, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\s*pagal\s+skonį\s*', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*\(patiekimui\)\s*', '', name, flags=re.IGNORECASE)
            name = self.clean_text(name).lower()
            
            try:
                amount = int(amount_str) if '.' not in amount_str and ',' not in amount_str else float(amount_str.replace(',', '.'))
            except:
                amount = amount_str
            
            return [{
                "name": name,
                "units": None,
                "amount": amount
            }]
        
        # Если ничего не подошло - просто название без количества
        name = re.sub(r'\([^)]*\)', '', text)
        name = re.sub(r'\s*pagal\s+skonį\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s*\(patiekimui\)\s*', '', name, flags=re.IGNORECASE)
        name = self.clean_text(name).lower()
        
        return [{
            "name": name,
            "units": None,
            "amount": None
        }]
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем все списки ul
        lists = article.find_all('ul')
        
        # Второй список обычно содержит ингредиенты
        if len(lists) >= 2:
            ingredient_list = lists[1]
            items = ingredient_list.find_all('li')
            
            ingredients = []
            for item in items:
                text = item.get_text(strip=True)
                parsed_list = self.parse_ingredient_item(text)
                if parsed_list:
                    ingredients.extend(parsed_list)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем упорядоченный список (ol) - обычно это инструкции
        ol = article.find('ol')
        if ol:
            steps = ol.find_all('li')
            instruction_texts = []
            
            for step in steps:
                text = step.get_text(strip=True)
                # Удаляем заголовки шагов типа "Paruoškite mėsą:"
                text = re.sub(r'^[^:]+:\s*', '', text)
                text = self.clean_text(text)
                instruction_texts.append(text)
            
            if instruction_texts:
                return ' '.join(instruction_texts)
        
        return None
    
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
                                # Возвращаем первую категорию
                                category = sections[0]
                                # Переводим некоторые категории на английский
                                if 'sriub' in category.lower():
                                    return "Soup"
                                elif 'deser' in category.lower() or 'pyrag' in category.lower():
                                    return "Dessert"
                                return category
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        article = self.soup.find('article')
        if not article:
            return None
        
        # Заметки обычно в параграфе, который содержит слова-маркеры
        # Ищем параграфы с длинным текстом, содержащие типичные слова
        paragraphs = article.find_all('p')
        
        # Пропускаем первые 4 параграфа (это обычно вступление и мета-текст)
        # Берем 5-й параграф, который обычно содержит заметки/советы
        if len(paragraphs) >= 5:
            notes_text = paragraphs[4].get_text(strip=True)
            # Проверяем, что это действительно заметки (длинный текст с советами)
            if len(notes_text) > 100:
                return self.clean_text(notes_text)
        
        # Альтернативный поиск - ищем по ключевым словам
        for p in paragraphs[4:]:
            text = p.get_text(strip=True)
            # Проверяем, содержит ли текст слова, характерные для заметок
            if any(word in text.lower() for word in ['galite', 'rekomenduoja', 'pabandyk', 'universali', 'eksperiment']):
                # Проверяем, что это не начало рецепта
                if len(text) > 100 and 'ingredientų' not in text.lower() and 'žingsniai' not in text.lower():
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # В примерах теги указаны вручную, но попробуем найти их
        # Можем использовать категорию как базу для тегов
        
        # Попытка 1: Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            return keywords.lower()
        
        # Попытка 2: Формируем из категории и названия
        category = self.extract_category()
        dish_name = self.extract_dish_name()
        
        tags = []
        if category:
            tags.append(category.lower())
        if dish_name:
            # Берем ключевые слова из названия
            words = dish_name.lower().split()
            tags.extend([w for w in words if len(w) > 3])
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
        # Извлекаем метаинформацию
        meta = self.extract_meta_info()
        
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": meta['prep_time'],
            "cook_time": meta['cook_time'],
            "total_time": meta['total_time'],
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "laferta_lt")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(LafertaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python laferta_lt.py")


if __name__ == "__main__":
    main()
