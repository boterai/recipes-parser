"""
Экстрактор данных рецептов для сайта mojbar.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MojbarPlExtractor(BaseRecipeExtractor):
    """Экстрактор для mojbar.pl"""
    
    def _find_content_div(self):
        """Находит div с основным контентом (содержит h2, ul, p)"""
        # Ищем все divs с классом tdb-block-inner
        divs = self.soup.find_all('div', class_='tdb-block-inner')
        
        # Ищем тот, который содержит h2 (заголовок рецепта)
        for div in divs:
            h2 = div.find('h2')
            if h2:
                return div
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из h2 в контенте (более точное название)
        content_div = self._find_content_div()
        if content_div:
            h2 = content_div.find('h2')
            if h2:
                title = self.clean_text(h2.get_text())
                # Убираем суффиксы типа " – Przepis na Drink"
                title = re.sub(r'\s*[–-]\s*Przepis\s+(na|Na)\s+Drink.*$', '', title, flags=re.IGNORECASE)
                # Убираем текст в скобках (польский перевод)
                title = re.sub(r'\s*\([^)]*\)', '', title)
                return title.strip()
        
        # Ищем в заголовке h1
        title_elem = self.soup.find('h1', class_='tdb-title-text')
        if title_elem:
            title = self.clean_text(title_elem.get_text())
            # Убираем суффиксы типа " – Przepis na Drink", " - Przepis Na Drink"
            title = re.sub(r'\s*[–-]\s*Przepis\s+(na|Na)\s+Drink.*$', '', title, flags=re.IGNORECASE)
            # Убираем текст в скобках
            title = re.sub(r'\s*\([^)]*\)', '', title)
            return title.strip()
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*[–-]\s*Przepis\s+(na|Na)\s+Drink.*$', '', title, flags=re.IGNORECASE)
            # Убираем текст в скобках
            title = re.sub(r'\s*\([^)]*\)', '', title)
            return self.clean_text(title).strip()
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в контенте (до h2 с названием рецепта)
        content_div = self._find_content_div()
        if content_div:
            # Ищем первый параграф перед h2
            for elem in content_div.children:
                if elem.name == 'p':
                    text = self.clean_text(elem.get_text())
                    if text and len(text) > 30:
                        # Извлекаем предложение, описывающее состав напитка
                        sentences = text.split('.')
                        for sent in sentences:
                            sent = sent.strip()
                            # Ищем предложение со словами "składa się" или "składający się"
                            if ('składaj' in sent.lower() and 'składnik' in sent.lower()) or 'są to' in sent.lower():
                                # Берем только релевантную часть
                                # "prosty drink składający się tylko z dwóch składników"
                                # "Są to czysta wódka i meksykański likier kawowy Kahlua"
                                # Объединяем их
                                desc_parts = []
                                for s in sentences:
                                    s = s.strip()
                                    if any(kw in s.lower() for kw in ['składaj', 'są to', 'składnik']):
                                        # Убираем начальные вводные фразы
                                        s = re.sub(r'^.*?(prosty drink|są to)', r'\1', s, flags=re.IGNORECASE).strip()
                                        s = re.sub(r'^prosty drink\s+', 'Prosty drink ', s, flags=re.IGNORECASE)
                                        s = re.sub(r'^są to\s+', '', s, flags=re.IGNORECASE)
                                        desc_parts.append(s)
                                
                                if desc_parts:
                                    # Объединяем части
                                    if len(desc_parts) >= 2:
                                        # "Prosty drink składający się tylko z dwóch składników: czysta wódka i..."
                                        return desc_parts[0] + ': ' + desc_parts[1] + '.'
                                    else:
                                        return desc_parts[0] + '.'
                        
                        # Если не нашли, берем первое предложение
                        return sentences[0].strip() + '.' if sentences else text
                elif elem.name == 'h2':
                    break
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "40 ml czystej wódki" или "wódka czysta – 40 ml"
            
        Returns:
            dict: {"name": "czysta wódka", "amount": 40, "units": "ml"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Формат 1: "название – количество единица" (используется в bomber, bull-shot)
        # Примеры: "wódka czysta – 40 ml", "angostura bitter – 3 dash"
        pattern1 = r'^(.+?)\s*[–-]\s*([\d.,]+)?\s*(.*)$'
        match1 = re.match(pattern1, text)
        
        if match1 and '–' in text or '-' in text:
            name, amount_str, units = match1.groups()
            name = name.strip()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    amount = float(amount_str)
                    if amount.is_integer():
                        amount = int(amount)
                except ValueError:
                    amount = amount_str
            
            # Обработка единицы измерения
            units = units.strip() if units and units.strip() else None
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Формат 2: "количество единица название" (используется в black-russian)
        # Примеры: "40 ml czystej wódki", "3 dash angostura bitter"
        pattern2 = r'^([\d.,]+)?\s*(ml|l|g|kg|dash|dashe|krople|kropla|szczypta|szczypt|do dekoracji|podle|według uznania)?\s*(.+)$'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            amount_str, units, name = match2.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    amount = float(amount_str)
                    if amount.is_integer():
                        amount = int(amount)
                except ValueError:
                    amount = amount_str
            
            # Обработка единицы измерения
            units = units.strip() if units and units.strip() else None
            
            # Обработка названия - убираем склонения (родительный падеж -> именительный)
            name = name.strip() if name else text
            
            # Преобразования для польских склонений
            name_fixes = {
                'czystej wódki': 'czysta wódka',
                'likieru kawowego': 'likier kawowy',
                'wódki czystej': 'wódka czysta',
                'likieru wiśniowego': 'likier wiśniowy',
                'rumu białego': 'rum biały',
                'tequili srebrnej': 'tequila srebrna',
                'soku z cytryny': 'sok z cytryny',
                'soku z limonki': 'sok z limonki',
                'limonki sok': 'limonka sok',
                'cytryny sok': 'cytryna sok',
                'syropu cukrowego': 'syrop cukrowy',
                'bitteru angostura': 'angostura bitter',
                'wystudzionego bulionu': 'wystudzony bulion',
                'sosu worcestershire': 'sos Worcestershire',
                'soli selerowej': 'sól selerowa'
            }
            
            name_lower = name.lower()
            for old, new in name_fixes.items():
                if old in name_lower:
                    name = new
                    break
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Если ничего не подошло, возвращаем как название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов
        content_div = self._find_content_div()
        if content_div:
            # Ищем первый ul после h2 с заголовком рецепта
            found_recipe_header = False
            for elem in content_div.children:
                if elem.name == 'h2':
                    found_recipe_header = True
                elif elem.name == 'ul' and found_recipe_header:
                    # Это список ингредиентов
                    items = elem.find_all('li', recursive=False)
                    
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    # Берем только первый список
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # В HTML mojbar.pl нет отдельной секции с инструкциями,
        # поэтому возвращаем None или создаем базовую инструкцию
        # на основе типа напитка
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Всегда возвращаем "Drink" для mojbar.pl, так как это сайт о напитках
        return "Drink"
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после ингредиентов с вариациями и советами
        content_div = self._find_content_div()
        if content_div:
            # Ищем текст после первого ul (список ингредиентов)
            found_ingredients_list = False
            
            for elem in content_div.children:
                if elem.name == 'ul' and not found_ingredients_list:
                    found_ingredients_list = True
                elif elem.name == 'p' and found_ingredients_list:
                    text = self.clean_text(elem.get_text())
                    
                    # Ищем текст с вариациями/заметками
                    if 'mrożonej wersji' in text.lower() or 'w tym celu' in text.lower():
                        # Извлекаем предложения о mrożonej wersji
                        sentences = text.split('.')
                        result_sentences = []
                        
                        for sent in sentences:
                            sent = sent.strip()
                            # Берем предложения с ключевыми словами
                            if any(kw in sent.lower() for kw in ['w tym celu', 'dodać', 'kulki lod', 'zmiksować']):
                                result_sentences.append(sent)
                        
                        if result_sentences:
                            note = '. '.join(result_sentences)
                            # Упрощаем формулировку
                            # "W tym celu należy po za klasycznymi składnikami w ilości 40 ml wódka i 20 ml likier kawowy Kahlua dodać..."
                            # -> "Dla mrożonej wersji dodać..."
                            note = re.sub(r'^W tym celu należy po za klasycznymi składnikami w ilości[^.]*\s+', 
                                        'Dla mrożonej wersji ', note)
                            return note + '.'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Создаем базовые теги
        tags = ['cocktail', 'drink']
        
        # Добавляем название
        dish_name = self.extract_dish_name()
        if dish_name:
            tags.append(dish_name)
        
        return ', '.join(tags)
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # WebPage с thumbnailUrl
                        elif item.get('@type') == 'WebPage' and 'thumbnailUrl' in item:
                            urls.append(item['thumbnailUrl'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
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
            "prep_time": None,  # Не найдено в HTML
            "cook_time": None,  # Не найдено в HTML
            "total_time": None,  # Не найдено в HTML
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/mojbar_pl
    recipes_dir = os.path.join("preprocessed", "mojbar_pl")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MojbarPlExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python mojbar_pl.py")


if __name__ == "__main__":
    main()
