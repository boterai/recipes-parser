"""
Экстрактор данных рецептов для сайта ninjatestkitchen.eu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NinjaTestKitchenExtractor(BaseRecipeExtractor):
    """Экстрактор для ninjatestkitchen.eu"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 min" или "1 hour 30 min"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} min" if minutes < 60 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta itemprop
        meta_name = self.soup.find('meta', attrs={'itemprop': 'name'})
        if meta_name and meta_name.get('content'):
            return self.clean_text(meta_name['content'])
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1', class_='text-uppercase')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+-\s+.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta itemprop
        meta_desc = self.soup.find('meta', attrs={'itemprop': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем только первое предложение (до первой точки)
            sentences = desc.split('.')
            if sentences:
                return self.clean_text(sentences[0] + '.')
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем только первое предложение
            sentences = desc.split('.')
            if sentences:
                return self.clean_text(sentences[0] + '.')
        
        # Альтернативно - из .single-summary
        summary = self.soup.find(class_='single-summary')
        if summary:
            p = summary.find('p')
            if p:
                text = p.get_text()
                sentences = text.split('.')
                if sentences:
                    return self.clean_text(sentences[0] + '.')
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов в metric группе
        metric_group = self.soup.find('div', class_='single-ingredients__group', attrs={'data-unit': 'metric'})
        
        if metric_group:
            # Извлекаем элементы списка с data-slug
            items = metric_group.find_all('li', attrs={'data-slug': True})
            
            for item in items:
                # Извлекаем количество и единицу измерения
                amount_span = item.find('span', class_='font-weight-semi-bold')
                
                amount = None
                unit = None
                name = None
                
                if amount_span:
                    # Получаем текст количества
                    amount_text = self.clean_text(amount_span.get_text())
                    
                    # Получаем название - это весь текст после span
                    full_text = item.get_text()
                    name_text = full_text.replace(amount_text, '', 1).strip()
                    name = self.clean_text(name_text)
                    
                    # Удаляем текст в скобках из названия
                    name = re.sub(r'\([^)]*\)', '', name).strip()
                    
                    # Парсим количество и единицу из amount_text
                    parsed_amount = self.parse_amount_and_unit(amount_text)
                    
                    # Парсим название для извлечения единиц измерения (например, "spicchi d'aglio" -> units="spicchi", name="aglio")
                    parsed_name = self.parse_name_and_extract_unit(name)
                    
                    amount = parsed_amount['amount']
                    # Приоритет: единица из названия, затем из количества
                    unit = parsed_name['unit'] if parsed_name['unit'] else parsed_amount['unit']
                    name = parsed_name['name']
                else:
                    # Если нет span, берем весь текст как название
                    name = self.clean_text(item.get_text())
                    # Удаляем текст в скобках
                    name = re.sub(r'\([^)]*\)', '', name).strip()
                    amount = None
                    unit = None
                
                if name:
                    # Проверяем, есть ли "e" (и) в названии с "A piacere" в количестве/unit
                    # Это означает составной ингредиент типа "sale e pepe"
                    if ' e ' in name and (amount == "A piacere" or unit == "A piacere"):
                        # Разбиваем на отдельные ингредиенты
                        parts = name.split(' e ')
                        for part in parts:
                            part = part.strip()
                            if part:
                                ingredients.append({
                                    "name": part,
                                    "units": None,
                                    "amount": "A piacere"
                                })
                    else:
                        ingredients.append({
                            "name": name,
                            "units": unit,
                            "amount": amount
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_amount_and_unit(self, text: str) -> dict:
        """
        Парсинг количества и единицы измерения
        
        Args:
            text: строка вида "1 cucchiaio" или "200 g" или "2" или "A piacere" или "1 grande"
            
        Returns:
            dict: {"amount": "1", "unit": "cucchiaio"} или {"amount": "2", "unit": None} или {"amount": "1 grande", "unit": None}
        """
        if not text:
            return {"amount": None, "unit": None}
        
        text = text.strip()
        
        # Проверяем специальные случаи
        if text.lower() == "a piacere":
            return {"amount": "A piacere", "unit": None}
        
        # Список прилагательных размера (не единицы измерения)
        size_adjectives = ['grande', 'piccolo', 'medio', 'piccola', 'media', 'grandi', 'piccoli', 'medi', 'medie']
        
        # Паттерн для извлечения количества и единицы
        # Поддерживает: "1", "1-2", "1/2", "1.5", "200 g", "1 cucchiaio", "1 grande"
        pattern = r'^([\d\s/.,\-]+)\s*(.*)$'
        
        match = re.match(pattern, text)
        
        if match:
            amount_str = match.group(1).strip()
            unit_str = match.group(2).strip()
            
            # Если unit_str - это прилагательное размера, оставляем его в amount
            if unit_str.lower() in size_adjectives:
                return {"amount": f"{amount_str} {unit_str}", "unit": None}
            
            # Очистка amount
            amount = amount_str if amount_str else None
            
            # Очистка unit
            unit = unit_str if unit_str else None
            
            return {"amount": amount, "unit": unit}
        
        # Если паттерн не совпал, проверяем - может это только текст (единица без количества)
        if not re.search(r'\d', text):
            return {"amount": None, "unit": text}
        
        return {"amount": text, "unit": None}
    
    def parse_name_and_extract_unit(self, name: str) -> dict:
        """
        Извлекает единицу измерения из названия ингредиента, если она там есть
        
        Args:
            name: строка вида "spicchi d'aglio" или "patata dolce" или "cumino"
            
        Returns:
            dict: {"name": "aglio", "unit": "spicchi"} или {"name": "patata dolce", "unit": None}
        """
        if not name:
            return {"name": None, "unit": None}
        
        name = name.strip()
        
        # Список единиц измерения, которые могут быть в начале названия
        # На итальянском языке (НЕ включаем прилагательные вроде "grande", "piccolo" и т.д.)
        units = [
            'spicchi', 'spicchio', 'fette', 'fetta', 'pezzi', 'pezzo',
            'cucchiai', 'cucchiaio', 'cucchiaini', 'cucchiaino',
            'tazze', 'tazza', 'bicchieri', 'bicchiere',
            'barattoli', 'barattolo', 'lattine', 'lattina',
            'borse', 'borsa', 'sacchetti', 'sacchetto',
            'pizzico', 'pizzichi', 'scatole', 'scatola'
        ]
        
        # Проверяем, начинается ли название с единицы измерения
        for unit in units:
            # Паттерн: "spicchi d'aglio" или "spicchi di aglio"
            pattern = rf'^{unit}\s+(d\'|di\s+)?(.+)$'
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                # Извлекаем название без единицы
                clean_name = match.group(2).strip()
                return {"name": clean_name, "unit": unit}
        
        # Если единица не найдена, возвращаем название как есть
        return {"name": name, "unit": None}
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из meta itemprop
        meta_instructions = self.soup.find('meta', attrs={'itemprop': 'recipeInstructions'})
        if meta_instructions and meta_instructions.get('content'):
            try:
                # Парсим JSON
                instructions_data = json.loads(meta_instructions['content'])
                
                if isinstance(instructions_data, list):
                    for idx, step in enumerate(instructions_data, 1):
                        if isinstance(step, dict) and 'text' in step:
                            step_text = self.clean_text(step['text'])
                            if step_text:
                                steps.append(f"{idx}. {step_text}")
                        elif isinstance(step, str):
                            step_text = self.clean_text(step)
                            if step_text:
                                steps.append(f"{idx}. {step_text}")
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Если не получилось из meta, ищем в HTML
        if not steps:
            step_containers = self.soup.find_all(class_='single-cooking-mode-modal__step')
            
            for container in step_containers:
                # Извлекаем текст шага
                p = container.find('p')
                if p:
                    step_text = self.clean_text(p.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Если нумерация не была добавлена, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta itemprop
        meta_category = self.soup.find('meta', attrs={'itemprop': 'recipeCategory'})
        if meta_category and meta_category.get('content'):
            return self.clean_text(meta_category['content'])
        
        # Альтернативно - из ссылок на категории
        category_links = self.soup.find_all('a', href=re.compile(r'/recipe_cat/'))
        if category_links:
            categories = [self.clean_text(link.get_text()) for link in category_links]
            categories = [cat for cat in categories if cat]
            if categories:
                return categories[0]  # Берем первую категорию
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Ищем в meta itemprop
        meta_time = self.soup.find('meta', attrs={'itemprop': time_type})
        if meta_time and meta_time.get('content'):
            iso_time = meta_time['content']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В ninjatestkitchen.eu заметки часто находятся в первом предложении описания
        # если оно содержит рекомендации (Delizioso servito, Compatibile, etc.)
        
        meta_desc = self.soup.find('meta', attrs={'itemprop': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем первое предложение
            sentences = desc.split('.')
            if len(sentences) > 0:
                first_sentence = sentences[0].strip()
                # Проверяем, содержит ли рекомендации/заметки
                keywords = ['delizioso', 'compatibil', 'servito', 'perfetto', 'ideale', 'ottimo']
                if any(keyword in first_sentence.lower() for keyword in keywords):
                    return self.clean_text(first_sentence + '.')
        
        # Ищем секцию с примечаниями
        notes_section = self.soup.find(class_=re.compile(r'recipe.*note', re.I))
        if notes_section:
            text = self.clean_text(notes_section.get_text())
            return text if text else None
        
        # Ищем параграфы после заголовка "Note" или "Nota"
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().lower()
            if 'note' in heading_text or 'nota' in heading_text:
                # Берем следующий параграф
                next_p = heading.find_next('p')
                if next_p:
                    text = self.clean_text(next_p.get_text())
                    return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Вариант 1: из meta keywords
        meta_keywords = self.soup.find('meta', attrs={'itemprop': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Вариант 2: из категорий рецепта
        if not tags_list:
            category_links = self.soup.find_all('a', href=re.compile(r'/recipe_cat/'))
            tags_list = [self.clean_text(link.get_text()) for link in category_links]
            tags_list = [tag for tag in tags_list if tag]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta itemprop
        meta_image = self.soup.find('meta', attrs={'itemprop': 'image'})
        if meta_image and meta_image.get('content'):
            urls.append(meta_image['content'])
        
        # 2. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image:src'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 4. Ищем в background-image стиле header.single-hero
        hero = self.soup.find('header', class_='single-hero')
        if hero and hero.get('style'):
            style = hero['style']
            # Извлекаем URL из background-image
            match = re.search(r'background-image:\s*url\(["\']?([^"\')]+)["\']?\)', style)
            if match:
                urls.append(match.group(1))
        
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
    # По умолчанию обрабатываем папку preprocessed/ninjatestkitchen_eu
    preprocessed_dir = os.path.join("preprocessed", "ninjatestkitchen_eu")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NinjaTestKitchenExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python ninjatestkitchen_eu.py")


if __name__ == "__main__":
    main()
