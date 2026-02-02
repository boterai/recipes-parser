"""
Экстрактор данных рецептов для сайта barracudamatera.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BarracudaMateraExtractor(BaseRecipeExtractor):
    """Экстрактор для barracudamatera.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        entry_title = self.soup.find('h1', class_='entry-title')
        if entry_title:
            title = self.clean_text(entry_title.get_text())
            # Убираем длинные подзаголовки после двоеточия
            if ':' in title:
                title = title.split(':')[0].strip()
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            if ':' in title:
                title = title.split(':')[0].strip()
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в entry-content (наиболее надежный способ)
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            first_p = entry_content.find('p')
            if first_p:
                text = self.clean_text(first_p.get_text())
                # Берем только первое предложение если текст длинный
                if len(text) > 200:
                    sentences = text.split('.')
                    if sentences:
                        return sentences[0].strip() + '.'
                return text
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 g di fiocchi di avena"
            
        Returns:
            dict: {"name": "fiocchi di avena", "amount": 200, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g di fiocchi di avena", "2 uova", "1 bustina di lievito per dolci"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|gr|grammi|kg|ml|l|litri|cucchiai?|cucchiaini?|bustine?|bustina|pizzico|medie?|medio|grandi?|grande)?(?:\s+di)?\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества - конвертируем в число где возможно
            amount = None
            if amount_str:
                amount_str = amount_str.replace(',', '.')
                try:
                    # Пробуем конвертировать в int если это целое число
                    if '.' not in amount_str:
                        amount = int(amount_str)
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = amount_str
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия
            name = name.strip()
            # Удаляем скобки с содержимым
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем фразы "facoltativo", "a piacere", "q.b."
            name = re.sub(r'\b(facoltativo|facoltativi|facoltativa|facoltative|a piacere|q\.?b\.?|opzionale)\b', '', name, flags=re.IGNORECASE)
            # Удаляем лишние пробелы и запятые
            name = re.sub(r'[,;]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Убираем частицы "medie", "medio" из названия и переносим в units
            medie_match = re.search(r'\b(medie?|medi[oa]|grandi?|grande|piccol[eoa])\b', name, re.IGNORECASE)
            if medie_match and not unit:
                unit = medie_match.group(1).lower()
                name = re.sub(r'\b(medie?|medi[oa]|grandi?|grande|piccol[eoa])\b', '', name, flags=re.IGNORECASE).strip()
            
            # Приводим название к нижнему регистру
            name = name.lower()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        else:
            # Если паттерн не совпал, пробуем без количества
            # Это может быть "sale", "cannella", "aromi a piacere"
            name = text
            unit = None
            
            # Проверяем на "facoltativa/e" в скобках
            # Если в скобках ТОЛЬКО facoltativ* (с запятой или без), то НЕ используем как unit
            # Если в скобках facoltativ* вместе с другим текстом, используем как unit
            facoltativ_match = re.search(r'\((facoltativ[aeo])(?:,\s*[^)]+)?\)', text, re.IGNORECASE)
            if facoltativ_match:
                # Проверяем, есть ли что-то кроме facoltativ* в скобках
                full_match = facoltativ_match.group(0)
                if ',' in full_match:  # Есть дополнительный текст после запятой
                    unit = 'facoltative'  # Используем множественное число для согласованности
                # Удаляем скобки с facoltativ*
                name = re.sub(r'\s*\([^)]*facoltativ[^)]*\)', '', text, flags=re.IGNORECASE)
            else:
                # Удаляем остатки скобок если facoltativ* не был найден
                name = re.sub(r'\([^)]*\)', '', text)
            
            # Удаляем фразы только если они стоят отдельно, но НЕ если они часть названия "aromi a piacere"
            if not re.search(r'aromi\s+a\s+piacere', name, re.IGNORECASE):
                name = re.sub(r'\b(facoltativo|facoltativi|facoltativa|facoltative|a piacere|q\.?b\.?|opzionale|un pizzico di)\b', '', name, flags=re.IGNORECASE)
            # Удаляем артикли и другие ненужные слова
            name = re.sub(r'\b(di un|di una|del|della)\b', 'di', name, flags=re.IGNORECASE)
            name = re.sub(r'\bgrattugiata?\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Удаляем запятые и другие знаки в начале/конце
            name = re.sub(r'^[,\s]+|[,\s]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Приводим название к нижнему регистру
            name = name.lower()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "units": unit,
                "amount": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с заголовком "Ingredienti:"
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим все h3 заголовки
        h3_tags = entry_content.find_all('h3')
        
        for h3 in h3_tags:
            h3_text = h3.get_text(strip=True)
            if re.search(r'Ingredienti', h3_text, re.IGNORECASE):
                # Находим следующий ul после этого заголовка
                next_ul = h3.find_next_sibling('ul')
                if next_ul:
                    # Извлекаем элементы списка
                    items = next_ul.find_all('li', recursive=False)
                    
                    for item in items:
                        # Извлекаем текст ингредиента
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим в структурированный формат
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с заголовком "Preparazione:"
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим все h3 заголовки
        h3_tags = entry_content.find_all('h3')
        
        for h3 in h3_tags:
            h3_text = h3.get_text(strip=True)
            if re.search(r'Preparazione', h3_text, re.IGNORECASE):
                # Находим следующий ol после этого заголовка
                next_ol = h3.find_next_sibling('ol')
                if next_ol:
                    # Извлекаем элементы списка
                    step_items = next_ol.find_all('li', recursive=False)
                    
                    for item in step_items:
                        # Извлекаем текст инструкции
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        # Удаляем фразы в скобках (опциональные детали)
                        step_text = re.sub(r'\([^)]*\)', '', step_text)
                        step_text = re.sub(r'\s+', ' ', step_text).strip()
                        
                        if step_text:
                            steps.append(step_text)
                    
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках (breadcrumb)
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        # Ищем категорию в тексте или из контекста страницы
        # Часто категория - "Dessert" для тортов
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Проверяем заголовок - если упоминается "torta", скорее всего это десерт
            title = self.extract_dish_name()
            if title and re.search(r'\b(torta|dolce|dessert)\b', title, re.IGNORECASE):
                return "Dessert"
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str = None) -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Паттерны для поиска времени в тексте
        # Примеры: "35-40 minuti", "30 minuti", "1 ora", "1 ora e 30 minuti"
        patterns = [
            r'(\d+(?:-\d+)?)\s*minut[oi]',  # "30 minuti", "35-40 minuti"
            r'(\d+)\s*or[ae]',  # "1 ora", "2 ore"
            r'(\d+)\s*or[ae]\s*e\s*(\d+)\s*minut[oi]',  # "1 ora e 30 minuti"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 1:
                    time_str = match.group(1)
                    # Проверяем, это минуты или часы
                    if 'minut' in match.group(0).lower():
                        return f"{time_str} minutes"
                    elif 'or' in match.group(0).lower():
                        # Конвертируем часы в минуты
                        hours = int(time_str)
                        return f"{hours * 60} minutes"
                elif len(match.groups()) == 2:
                    # Часы и минуты
                    hours = int(match.group(1))
                    minutes = int(match.group(2))
                    total_minutes = hours * 60 + minutes
                    return f"{total_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с упоминанием времени подготовки
        text = entry_content.get_text()
        
        # Ищем упоминания "tempo di preparazione"
        prep_pattern = r'tempo\s+di\s+preparazione[:\s]+(?:circa\s+)?(\d+(?:-\d+)?)\s*minut[oi]'
        
        match = re.search(prep_pattern, text, re.IGNORECASE)
        if match:
            time_str = match.group(1)
            return f"{time_str} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с упоминанием времени готовки
        text = entry_content.get_text()
        
        # Сначала пробуем найти "tempo di cottura"
        cook_time_pattern = r'tempo\s+di\s+cottura[:\s]+(\d+(?:-\d+)?)\s*minut[oi]'
        match = re.search(cook_time_pattern, text, re.IGNORECASE)
        if match:
            time_str = match.group(1)
            return f"{time_str} minutes"
        
        # Если не нашли, ищем упоминания "cuocere", "infornare"
        cook_patterns = [
            r'cuocere.*?per\s+circa\s+(\d+(?:-\d+)?)\s*minut[oi]',
            r'infornare.*?per\s+circa\s+(\d+(?:-\d+)?)\s*minut[oi]',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                return f"{time_str} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с упоминанием общего времени
        text = entry_content.get_text()
        
        # Ищем упоминания "tempo totale"
        total_pattern = r'tempo\s+totale[:\s]+(\d+(?:-\d+)?)\s*minut[oi]'
        
        match = re.search(total_pattern, text, re.IGNORECASE)
        if match:
            time_str = match.group(1)
            return f"{time_str} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем конкретные фразы в тексте, которые указывают на заметки о вариантах
        text_content = entry_content.get_text()
        
        # Паттерны для поиска заметок о вариантах рецепта
        note_patterns = [
            r'La ricetta[^.]+può essere facilmente adattata[^.]+\.',
            r'La ricetta base[^.]+è un ottimo punto di partenza[^.]+\.',
            r'Può essere personalizzata[^.]+\.',
        ]
        
        for pattern in note_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE | re.DOTALL)
            if match:
                note_text = match.group(0)
                note_text = self.clean_text(note_text)
                # Обрезаем до разумной длины
                if len(note_text) > 500:
                    sentences = note_text.split('.')
                    if sentences:
                        return sentences[0].strip() + '.'
                return note_text
        
        # Если не нашли в основном тексте, ищем в списках вариантов
        # Например "Variazioni di farina" / "Versione vegana"
        h2_tags = entry_content.find_all('h2')
        for h2 in h2_tags:
            if 'varianti' in h2.get_text().lower() or 'consigli' in h2.get_text().lower():
                # Находим следующий ul после заголовка
                next_ul = h2.find_next_sibling('ul')
                if next_ul:
                    # Ищем пункты списка с ключевыми фразами
                    items = next_ul.find_all('li')
                    for item in items:
                        item_text = item.get_text()
                        if re.search(r'può essere personalizzata|versione vegana', item_text, re.IGNORECASE):
                            # Берем текст пункта
                            text = self.clean_text(item_text)
                            # Извлекаем первое предложение
                            sentences = text.split('.')
                            if len(sentences) >= 2:
                                return sentences[0].strip() + '. ' + sentences[1].strip() + '.'
                            return text if len(text) < 200 else text[:200] + '...'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Ищем в мета-тегах keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Ищем теги в article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        if article_tags:
            for tag_meta in article_tags:
                if tag_meta.get('content'):
                    tags_list.append(tag_meta['content'])
        
        # 3. Если не нашли, извлекаем основные ключевые слова из заголовка
        if not tags_list:
            title = self.extract_dish_name()
            if title:
                title_lower = title.lower()
                # Извлекаем только самые важные ключевые слова
                if 'torta' in title_lower:
                    tags_list.append('Torta')
                # Основные ингредиенты из заголовка
                if 'marmellata' in title_lower:
                    tags_list.append('Marmellata')
                if 'mele' in title_lower:
                    tags_list.append('Mele')
                if 'avena' in title_lower:
                    tags_list.append('Avena')
                    
                # Добавляем категорию
                category = self.extract_category()
                if category and category not in tags_list:
                    tags_list.append(category)
        
        if not tags_list:
            return None
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем изображения в контенте статьи
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            img_tags = entry_content.find_all('img')
            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    # Фильтруем изображения (исключаем иконки, логотипы)
                    if not re.search(r'(icon|logo|sprite|avatar|emoji)', src, re.IGNORECASE):
                        urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
            return ','.join(unique_urls) if unique_urls else None
        
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
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/barracudamatera_it
    preprocessed_dir = os.path.join("preprocessed", "barracudamatera_it")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BarracudaMateraExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python barracudamatera_it.py")


if __name__ == "__main__":
    main()
