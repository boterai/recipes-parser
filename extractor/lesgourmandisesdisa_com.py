"""
Экстрактор данных рецептов для сайта lesgourmandisesdisa.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LesgourmandisesdisaComExtractor(BaseRecipeExtractor):
    """Экстрактор для lesgourmandisesdisa.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке поста
        title_elem = self.soup.find('h3', class_='entry-title')
        if title_elem:
            return self.clean_text(title_elem.get_text())
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Убираем "..." в конце если есть
            desc = re.sub(r'\s*\.\.\.$', '', desc)
            return self.clean_text(desc)
        
        # Пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'description' in data:
                    desc = data['description']
                    desc = re.sub(r'\s*\.\.\.$', '', desc)
                    return self.clean_text(desc)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Получаем весь текст
        text = post_body.get_text(separator='\n', strip=True)
        
        # Разбиваем на строки
        lines = text.split('\n')
        
        ingredients = []
        in_ingredients_section = False
        
        # Ищем секцию с ингредиентами
        # Обычно после "Pour X personnes" или "Pour X pots" или "Pour un moule" начинаются ингредиенты
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Начало секции ингредиентов - более гибкий паттерн
            # Ищем "Pour" в начале строки (с цифрами, или словами типа "un moule", "personnes", и т.д.)
            if re.match(r'^Pour\s+', line, re.IGNORECASE):
                in_ingredients_section = True
                continue
            
            # Пропускаем заголовки подсекций (например, "Grimolle :", "Croûte d'amandes")
            if in_ingredients_section and re.match(r'^[A-Z][a-zéèêàù\s]+\s*:?\s*$', line):
                continue
            
            # Конец секции ингредиентов - когда начинаются инструкции
            # Инструкции обычно начинаются с глаголов действия
            if in_ingredients_section and (
                line.lower().startswith(('blanchir', 'mélanger', 'ajouter', 'préchauffer', 
                                        'versez', 'pelez', 'couvrir', 'réduire', 'enfourner',
                                        'démoulez', 'préparez', 'fouettez', 'cuire', 'faire'))
                or line.lower().startswith('imprimer')
            ):
                break
            
            if in_ingredients_section:
                # Парсим ингредиент
                parsed = self.parse_ingredient_fr(line)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_fr(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на французском в структурированный формат
        
        Args:
            ingredient_text: Строка вида "8 pommes épluchées" или "1/2 tasse de sirop d'érable"
            
        Returns:
            dict: {"name": "pommes", "amount": "8", "units": "pieces"} или None
        """
        if not ingredient_text or len(ingredient_text) < 3:
            return None
        
        text = self.clean_text(ingredient_text).lower()
        
        # Пропускаем слишком длинные строки (скорее всего это инструкции)
        if len(text) > 150:
            return None
        
        # Удаляем содержимое в скобках перед парсингом (например, "(100 g)")
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Заменяем дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Французские единицы измерения (non-capturing groups для вложенных альтернатив)
        units_pattern = (
            r'(?:tasses?|tasse|cuillères?\s+à\s+(?:soupe|table|thé|café)|'
            r'c\.\s*à\s*(?:s|c|soupe|table|thé)|'
            r'ml|litre|l|'
            r'grammes?|g|kg|kilogrammes?|'
            r'pots?|morceaux?|tranches?|'
            r'gousses?|pincées?|branches?|'
            r'sachets?|paquets?|boîtes?|'
            r'entiers?|entières?|'
            r'livres?)'
        )
        
        # Паттерн: количество + единица + название
        # Примеры: "8 pommes", "1/2 tasse de sirop", "2 oeufs entiers"
        pattern = rf'^([\d\s/.,]+)?\s*({units_pattern})?\s*(?:de\s+|d\')?(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если нет количества, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        groups = match.groups()
        amount_str = groups[0]
        unit = groups[1]
        name = groups[2]
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(total)
            else:
                amount = amount_str.replace(',', '.').strip()
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip()
            # Нормализация единиц
            unit = re.sub(r'cuillères?\s+à\s+soupe', 'c. à soupe', unit)
            unit = re.sub(r'cuillères?\s+à\s+table', 'c. à s.', unit)
            unit = re.sub(r'cuillères?\s+à\s+thé', 'c. à thé', unit)
            unit = re.sub(r'cuillères?\s+à\s+café', 'c. à c.', unit)
            # Убираем лишние точки в конце
            unit = re.sub(r'\.+$', '', unit)
            # Добавляем точку после "s" в "c. à s" если её нет
            if unit == 'c. à s':
                unit = 'c. à s.'
            if unit == 'c. à c':
                unit = 'c. à c.'
        
        # Очистка названия
        name = name.strip() if name else None
        if name:
            # Удаляем "de " в начале
            name = re.sub(r'^de\s+', '', name)
            # Удаляем "d'" в начале  
            name = re.sub(r'^d\'\s*', '', name)
            # Удаляем ведущие точки и пробелы
            name = re.sub(r'^[\.\s]+', '', name)
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Нормализуем unit в units для совместимости с reference
        return {
            "name": name,
            "amount": float(amount) if amount and '.' in amount else int(amount) if amount and amount.replace('.','').isdigit() else amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Получаем весь текст
        text = post_body.get_text(separator='\n', strip=True)
        lines = text.split('\n')
        
        instructions = []
        in_instructions = False
        passed_ingredients = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Пропускаем секцию "Pour ..." (начало ингредиентов)
            if re.match(r'^Pour\s+', line, re.IGNORECASE):
                passed_ingredients = True
                continue
            
            # Начало инструкций - обычно после ингредиентов
            # Ищем строки, начинающиеся с глаголов действия
            if passed_ingredients and (
                line.lower().startswith(('blanchir', 'mélanger', 'ajouter', 'préchauffer', 
                                        'versez', 'pelez', 'couvrir', 'réduire', 'enfourner',
                                        'démoulez', 'préparez', 'fouettez', 'cuire', 'faire',
                                        'chemisez', 'lissez', 'pendant', 'sortir', 'remettre',
                                        'dans'))
            ):
                in_instructions = True
            
            # Конец инструкций
            if line.lower().startswith('imprimer'):
                break
            
            if in_instructions:
                # Пропускаем слишком короткие строки
                if len(line) > 15:
                    cleaned = self.clean_text(line)
                    if cleaned:
                        instructions.append(cleaned)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Попробуем из хлебных крошек или навигации
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        # Попробуем извлечь из текста поста - ищем упоминания категорий
        post_body = self.soup.find('div', class_='post-body')
        if post_body:
            text = post_body.get_text().lower()
            # Определяем категорию по ключевым словам
            if any(word in text for word in ['dessert', 'gâteau', 'tarte', 'biscuit', 'cannelé']):
                return 'Dessert'
            elif any(word in text for word in ['entrée', 'salade', 'soupe']):
                return 'Entrée'
            elif any(word in text for word in ['plat', 'viande', 'poisson']):
                return 'Plat principal'
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """Извлечение времени из текста"""
        if not text:
            return None
        
        # Ищем паттерны времени во французском тексте
        # "30 à 45 minutes", "24 heures", "1 heure 30"
        patterns = [
            r'(\d+)\s*(?:à|-)?\s*(\d+)?\s*(?:minutes?|min)',
            r'(\d+)\s*heures?\s*(?:(\d+)\s*(?:minutes?|min))?',
            r'au moins (\d+)\s*heures?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if 'heure' in text.lower():
                    hours = int(match.group(1))
                    minutes = int(match.group(2)) if match.group(2) else 0
                    if 'au moins' in text.lower():
                        return f"{hours} hours"
                    return f"{hours} hours {minutes} minutes" if minutes else f"{hours} hours"
                else:
                    # Минуты
                    min1 = int(match.group(1))
                    min2 = int(match.group(2)) if match.group(2) else None
                    if min2:
                        return f"{min1}-{min2} minutes"
                    return f"{min1} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        post_body = self.soup.find('div', class_='post-body')
        if post_body:
            text = post_body.get_text()
            # Ищем упоминания о времени подготовки
            if 'réserver au réfrigérateur' in text.lower() or 'repos' in text.lower():
                return self.extract_time_from_text(text, 'prep')
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        post_body = self.soup.find('div', class_='post-body')
        if post_body:
            text = post_body.get_text()
            # Ищем упоминания о времени готовки/выпечки
            return self.extract_time_from_text(text, 'cook')
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Можем попробовать суммировать prep + cook, но проще извлечь из текста
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Получаем текст
        text = post_body.get_text(separator='\n', strip=True)
        
        # Ищем текст в скобках внутри ингредиентов
        # Например: "( le sirop de catégorie B peut convenir: le goût est plus prononcé )"
        matches = re.findall(r'\(\s*([^)]{15,})\s*\)', text)
        
        notes = []
        for match in matches:
            # Фильтруем измерения в скобках
            if not re.match(r'^\d+\s*(ml|g|kg|cm)', match.lower()):
                cleaned = self.clean_text(match)
                if len(cleaned) > 10:
                    # Убираем двоеточия и очищаем
                    cleaned = re.sub(r':\s*', ': ', cleaned)
                    notes.append(cleaned)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Попробуем из keywords meta
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Попробуем извлечь из лейблов Blogger
        post_labels = self.soup.find('span', class_='post-labels')
        if post_labels:
            labels = post_labels.find_all('a', rel='tag')
            if labels:
                tags = [self.clean_text(label.get_text()).lower() for label in labels]
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Из post-body
        post_body = self.soup.find('div', class_='post-body')
        if post_body:
            images = post_body.find_all('img')
            for img in images[:3]:  # Берем первые 3 изображения
                src = img.get('src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Удаляем дубликаты
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем директорию preprocessed/lesgourmandisesdisa_com
    preprocessed_dir = os.path.join("preprocessed", "lesgourmandisesdisa_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LesgourmandisesdisaComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lesgourmandisesdisa_com.py")


if __name__ == "__main__":
    main()
