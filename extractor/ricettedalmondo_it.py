"""
Экстрактор данных рецептов для сайта ricettedalmondo.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RicetteDalMondoExtractor(BaseRecipeExtractor):
    """Экстрактор для ricettedalmondo.it"""
    
    def _get_json_ld_recipe(self) -> Optional[Dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с текстом
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes", например "90 minutes"
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
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_=re.compile('title', re.I))
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Ricetta|RicetteDalMondo).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
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
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Сначала ищем в HTML div#ingredienti
        ing_section = self.soup.find('div', id='ingredienti')
        if ing_section:
            # Ищем все списки ингредиентов
            uls = ing_section.find_all('ul')
            
            for ul in uls:
                items = ul.find_all('li')
                for item in items:
                    text = item.get_text().strip()
                    if not text:
                        continue
                    
                    # Парсим ингредиент
                    # Формат: "500 gr di farina 00" или "3 uova (intere)"
                    ingredient = self._parse_ingredient(text)
                    if ingredient:
                        ingredients_list.append(ingredient)
        
        if ingredients_list:
            # Возвращаем как JSON строку
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def _parse_ingredient(self, text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента
        
        Args:
            text: строка типа "500 gr di farina 00" или "3 uova (intere)"
            
        Returns:
            Dict с полями name, amount, units
        """
        text = self.clean_text(text)
        
        # Паттерны для извлечения количества, единиц и названия
        # Формат 1: "500 gr di farina 00"
        pattern1 = r'^([\d,./]+)\s*([a-zA-Z]+)?\s+di\s+(.+)$'
        match = re.match(pattern1, text, re.I)
        if match:
            amount = match.group(1).strip()
            unit = match.group(2).strip() if match.group(2) else None
            name = match.group(3).strip()
            return {
                "name": name,
                "units": unit,
                "amount": amount if amount else None
            }
        
        # Формат 2: "3 uova (intere)" или "1 arancia"
        pattern2 = r'^([\d,./]+)\s+(.+)$'
        match = re.match(pattern2, text, re.I)
        if match:
            amount = match.group(1).strip()
            name = match.group(2).strip()
            
            # Проверяем, есть ли единица в скобках
            unit_match = re.search(r'\(([^)]+)\)$', name)
            unit = None
            if unit_match:
                unit = unit_match.group(1)
                name = name[:unit_match.start()].strip()
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Формат 3: "q.b. di olio di semi" (количество по вкусу)
        pattern3 = r'^q\.b\.\s+di\s+(.+)$'
        match = re.match(pattern3, text, re.I)
        if match:
            name = match.group(1).strip()
            return {
                "name": name,
                "units": "q.b.",
                "amount": None
            }
        
        # Формат 4: просто название без количества
        # "sale"
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions_text = []
        
        # Сначала пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for i, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        instructions_text.append(f"{i}. {step_text}")
                    elif isinstance(step, str):
                        instructions_text.append(f"{i}. {self.clean_text(step)}")
                
                if instructions_text:
                    return ' '.join(instructions_text)
        
        # Если JSON-LD не помог, ищем в HTML
        prep_section = self.soup.find('div', id='preparazione')
        if prep_section:
            # Ищем все шаги (divы с классом step)
            steps = prep_section.find_all('div', class_='instruction')
            
            for i, step in enumerate(steps, 1):
                # Извлекаем текст шага (исключая заголовок h3)
                h3 = step.find('h3')
                if h3:
                    h3.extract()
                
                step_text = step.get_text().strip()
                if step_text:
                    instructions_text.append(f"{i}. {self.clean_text(step_text)}")
        
        if instructions_text:
            return ' '.join(instructions_text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'recipeCategory' in json_ld:
            return self.clean_text(json_ld['recipeCategory'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('div', class_='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a', class_='pathway')
            # Берем последнюю ссылку (обычно это категория)
            if links:
                last_link = links[-1]
                return self.clean_text(last_link.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Ищем в HTML в dati-ricetta
        dati = self.soup.find('div', class_='dati-ricetta')
        if dati:
            # Ищем div с классом tprep
            divs = dati.find_all('div')
            for div in divs:
                tprep = div.find('span', class_='tprep')
                if tprep:
                    # Следующий элемент - время
                    time_text = div.get_text().strip()
                    # Убираем пустой span
                    time_text = re.sub(r'^\s*$', '', time_text, flags=re.M)
                    time_text = ' '.join(time_text.split())
                    if time_text:
                        # Преобразуем "40 minuti" в "40 minutes"
                        time_text = re.sub(r'minuti?', 'minutes', time_text, flags=re.I)
                        time_text = re.sub(r'ore?', 'hours', time_text, flags=re.I)
                        return self.clean_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Ищем в HTML в dati-ricetta
        # Согласно reference JSON, нужно использовать trip (время отдыха) как cook_time
        # Если trip = "-", то используем tcott
        dati = self.soup.find('div', class_='dati-ricetta')
        if dati:
            divs = dati.find_all('div')
            
            # Ищем trip (время отдыха/riposo) - используется как cook_time в reference
            for div in divs:
                trip = div.find('span', class_='trip')
                if trip:
                    time_text = div.get_text().strip()
                    time_text = re.sub(r'^\s*$', '', time_text, flags=re.M)
                    time_text = ' '.join(time_text.split())
                    
                    # Если время не "-", используем его
                    if time_text and time_text != '-':
                        time_text = re.sub(r'minuti?', 'minutes', time_text, flags=re.I)
                        time_text = re.sub(r'ore?', 'hours', time_text, flags=re.I)
                        return self.clean_text(time_text)
            
            # Если trip = "-" или не найден, ищем tcott (время готовки)
            for div in divs:
                tcott = div.find('span', class_='tcott')
                if tcott:
                    time_text = div.get_text().strip()
                    time_text = re.sub(r'^\s*$', '', time_text, flags=re.M)
                    time_text = ' '.join(time_text.split())
                    if time_text and time_text != '-':
                        time_text = re.sub(r'minuti?', 'minutes', time_text, flags=re.I)
                        time_text = re.sub(r'ore?', 'hours', time_text, flags=re.I)
                        return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Если нет в JSON-LD, пытаемся вычислить
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            
            if prep_match and cook_match:
                total = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов"""
        # Ищем секцию с советами
        consigli = self.soup.find('div', id='consigli')
        if consigli:
            # Извлекаем текст из всех параграфов
            paragraphs = consigli.find_all('p')
            if paragraphs:
                notes_text = ' '.join([self.clean_text(p.get_text()) for p in paragraphs if p.get_text().strip()])
                if notes_text:
                    return notes_text
        
        # Альтернативно ищем в descrizione
        descrizione = self.soup.find('div', id='descrizione')
        if descrizione:
            # Берем первый параграф как заметку
            first_p = descrizione.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join([self.clean_text(k) for k in keywords])
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Пытаемся из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld:
            # Основное изображение
            if 'image' in json_ld:
                img = json_ld['image']
                if isinstance(img, str):
                    image_urls.append(img)
                elif isinstance(img, list):
                    image_urls.extend(img)
                elif isinstance(img, dict) and 'url' in img:
                    image_urls.append(img['url'])
            
            # Изображения из инструкций
            if 'recipeInstructions' in json_ld:
                for step in json_ld['recipeInstructions']:
                    if isinstance(step, dict) and 'image' in step:
                        image_urls.append(step['image'])
        
        # Также ищем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url not in image_urls:
                image_urls.append(img_url)
        
        if image_urls:
            return ','.join(image_urls)
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки HTML файлов ricettedalmondo.it
    """
    import os
    
    # Ищем директорию с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "ricettedalmondo_it")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(RicetteDalMondoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python ricettedalmondo_it.py")


if __name__ == "__main__":
    main()
