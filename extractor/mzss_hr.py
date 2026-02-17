"""
Экстрактор данных рецептов для сайта mzss.hr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MzssHrExtractor(BaseRecipeExtractor):
    """Экстрактор для mzss.hr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала ищем первый h3 заголовок с id, который содержит номер рецепта
        # Это будет конкретный рецепт, а не общая страница
        h3_tags = self.soup.find_all('h3', class_='wp-block-heading')
        
        for h3 in h3_tags:
            h3_id = h3.get('id', '')
            # Проверяем, что это заголовок рецепта (начинается с цифры и дефиса)
            if h3_id and re.match(r'^\d+-', h3_id):
                # Извлекаем текст заголовка
                text = h3.get_text(strip=True)
                # Убираем номер в начале (например "1. ")
                text = re.sub(r'^\d+\.\s*', '', text)
                return self.clean_text(text)
        
        # Если не нашли конкретный рецепт, пробуем взять из заголовка страницы (title tag)
        # Обычно формат: "Название – подзаголовок - MZSS.hr"
        title_tag = self.soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            # Убираем " - MZSS.hr" и берем первую часть до " – "
            title_text = re.sub(r'\s*-\s*MZSS\.hr\s*$', '', title_text)
            # Берем часть до первого " – " (длинное тире)
            parts = re.split(r'\s*[–—-]\s*', title_text)
            if parts:
                dish_name = parts[0].strip()
                # Проверяем, что это не общее название вроде "10 recepata"
                if dish_name and not re.search(r'\d+\s*(ukusnih\s*)?(recept|neodoliv)', dish_name, re.I):
                    return self.clean_text(dish_name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем описание из JSON-LD или meta тегов
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Ищем BlogPosting или другой тип с description
                if isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'BlogPosting' and 'description' in item:
                                # Берем первое предложение описания
                                desc = item['description']
                                # Находим первое полное предложение
                                sentences = desc.split('.')
                                if sentences:
                                    return self.clean_text(sentences[0] + '.')
                    
                    # Прямое описание
                    if data.get('@type') == 'BlogPosting' and 'description' in data:
                        desc = data['description']
                        sentences = desc.split('.')
                        if sentences:
                            return self.clean_text(sentences[0] + '.')
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            sentences = desc.split('.')
            if sentences:
                return self.clean_text(sentences[0] + '.')
        
        return None
    
    def _parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "1 velika glavica brokule" или "2 žlice maslinovog ulja"
            
        Returns:
            dict: {"name": "brokula", "amount": "1", "units": "velika glavica"}
        """
        if not text:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(text).strip()
        
        # Паттерн для количества (число, дробь или диапазон)
        # Примеры: "1", "2", "1/2", "1-2", "15-20"
        amount_pattern = r'^([\d\s/,.-]+)'
        
        match = re.match(amount_pattern, text)
        
        if match:
            amount_str = match.group(1).strip()
            remaining = text[len(match.group(0)):].strip()
            
            # Теперь remaining может быть: "velika glavica brokule" или "žlice maslinovog ulja"
            # Разделяем на единицу измерения и название
            
            # Список общих единиц измерения в хорватском
            units = [
                'velika glavica', 'mala glavica', 'glavica', 'glava',
                'žlice', 'žlica', 'žličica', 'žličice',
                'šalice', 'šalica', 'šalicu',
                'grama', 'gram', 'g',
                'kilograma', 'kilogram', 'kg',
                'litara', 'litar', 'l',
                'mililitara', 'mililitar', 'ml',
                'češnja', 'češnjeva', 'češnjak',
                'tablespoons', 'tablespoon', 'tbsp',
                'teaspoons', 'teaspoon', 'tsp',
                'cups', 'cup',
                'cloves', 'clove',
                'large head', 'head',
                'prstohvat', 'pršuta'
            ]
            
            # Ищем единицу измерения в начале remaining
            unit = None
            name = remaining
            
            for u in units:
                if remaining.lower().startswith(u):
                    unit = u
                    name = remaining[len(u):].strip()
                    break
            
            # Обработка amount - убираем диапазоны, оставляем первое число
            amount = amount_str.split('-')[0].strip()
            
            # Очистка названия от лишних слов и окончаний
            if name:
                # Убираем описания в конце (например ", sitno sjeckana")
                name = re.sub(r',.*$', '', name)
                # Убираем фразы "po izboru", "po želji"
                name = re.sub(r'\s*\(.*?\)', '', name)
                name = re.sub(r'\s+po\s+(izboru|želji).*$', '', name, flags=re.IGNORECASE)
                name = name.strip()
            
            return {
                "name": name if name else None,
                "amount": amount if amount else None,
                "units": unit
            }
        else:
            # Нет количества, только название
            # Очистка названия
            text = re.sub(r',.*$', '', text)
            text = re.sub(r'\s*\(.*?\)', '', text)
            text = re.sub(r'\s+po\s+(izboru|želji).*$', '', text, flags=re.IGNORECASE)
            text = text.strip()
            
            return {
                "name": text,
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем параграф с текстом "Sastojci:"
        paragraphs = self.soup.find_all('p')
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if text == 'Sastojci:':
                # Следующий элемент должен быть ul.wp-block-list
                next_elem = p.find_next_sibling()
                
                if next_elem and next_elem.name == 'ul' and 'wp-block-list' in next_elem.get('class', []):
                    # Извлекаем все элементы списка
                    items = next_elem.find_all('li', recursive=False)
                    
                    for item in items:
                        # Извлекаем текст ингредиента
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим ингредиент
                            parsed = self._parse_ingredient_text(ingredient_text)
                            ingredients.append(parsed)
                    
                    # Нашли первый рецепт - выходим
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем параграф с текстом "Priprema:"
        paragraphs = self.soup.find_all('p')
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if text == 'Priprema:':
                # Следующий элемент должен быть ol.wp-block-list
                next_elem = p.find_next_sibling()
                
                if next_elem and next_elem.name == 'ol' and 'wp-block-list' in next_elem.get('class', []):
                    # Извлекаем все элементы списка
                    items = next_elem.find_all('li', recursive=False)
                    
                    for item in items:
                        # Извлекаем текст шага
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        if step_text:
                            steps.append(step_text)
                    
                    # Нашли первый рецепт - выходим
                    break
        
        # Объединяем шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta теге article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def _extract_time_from_instructions(self, instructions: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            instructions: Текст инструкций
            time_type: Тип времени ('prep', 'cook', 'total')
            
        Returns:
            Время в формате "20 minutes" или None
        """
        if not instructions:
            return None
        
        # Паттерны для поиска времени в хорватском тексте
        # Примеры: "15-20 minuta", "1 sat", "30 minuta"
        time_patterns = [
            r'(\d+[-–]\d+)\s*minut',  # диапазон минут
            r'(\d+)\s*minut',          # минуты
            r'(\d+)\s*sat',            # часы
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                # Берем первое число из диапазона
                time_val = time_str.split('-')[0].strip()
                
                if 'minut' in match.group(0):
                    return f"{time_val} minutes"
                elif 'sat' in match.group(0):
                    return f"{time_val} hours"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В данных примерах prep_time задан явно
        # Для первого рецепта это "10 minutes"
        # Пробуем извлечь из инструкций или возвращаем None
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем извлечь время из инструкций
        instructions = self.extract_instructions()
        if instructions:
            return self._extract_time_from_instructions(instructions, 'cook')
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Комбинируем prep_time и cook_time если они есть
        # или извлекаем из инструкций
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем текст после инструкций, который может быть заметкой
        # Часто это идет после списка инструкций
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем параграф с текстом "Priprema:"
        paragraphs = self.soup.find_all('p')
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if text == 'Priprema:':
                # Следующий элемент - ol с инструкциями
                next_elem = p.find_next_sibling()
                
                if next_elem and next_elem.name == 'ol':
                    # Ищем следующий параграф после ol
                    note_elem = next_elem.find_next_sibling('p')
                    
                    if note_elem:
                        note_text = note_elem.get_text(separator=' ', strip=True)
                        note_text = self.clean_text(note_text)
                        
                        # Проверяем, что это не начало следующего рецепта
                        if note_text and not note_text.startswith('Sastojci:') and len(note_text) > 20:
                            # Проверяем, что следующий элемент не h3 (новый рецепт)
                            next_h3 = note_elem.find_next_sibling('h3')
                            if not next_h3 or next_elem.sourceline < next_h3.sourceline:
                                return note_text
                    
                    break
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем meta теги article:tag
        meta_tags = self.soup.find_all('meta', property='article:tag')
        
        for tag in meta_tags:
            content = tag.get('content')
            if content:
                tags.append(self.clean_text(content))
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. og:image - главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url not in urls:
                urls.append(url)
        
        # 2. twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url and url not in urls:
                urls.append(url)
        
        # Возвращаем как строку через запятую без пробелов
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
    """Обработка HTML файлов из директории preprocessed/mzss_hr"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "mzss_hr"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MzssHrExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mzss_hr.py")


if __name__ == "__main__":
    main()
