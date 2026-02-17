"""
Экстрактор данных рецептов для сайта happilyhomebaked.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HappilyHomeBakedExtractor(BaseRecipeExtractor):
    """Экстрактор для happilyhomebaked.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h2 заголовке с id начинающимся с "h-"
        # Пропускаем заголовки вроде "Key Ingredients", "Equipment", "Flavor Variations"
        skip_patterns = [
            r'key\s+ingredients',
            r'equipment',
            r'flavor\s+variations',
            r'faq',
            r'how\s+(do|to)',
            r'tips',
            r'substitutions'
        ]
        
        h2_tags = self.soup.find_all('h2', id=re.compile(r'^h-'))
        for h2 in h2_tags:
            text = self.clean_text(h2.get_text())
            
            # Проверяем, не является ли это служебным заголовком
            is_skip = False
            for pattern in skip_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    is_skip = True
                    break
            
            if not is_skip and text and len(text) > 3:
                return text
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|Happily Home Baked).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+(Recipe|Happily Home Baked).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
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
    
    def parse_ingredient_item(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 1/2 cups all-purpose flour" или "1 tsp salt"
            
        Returns:
            dict: {"name": "all-purpose flour", "amount": 2.5, "units": "cups"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживаем: "2 1/2 cups flour", "1 tsp salt", "4 to 7 apples", "pinch salt"
        # Важно: количество не должно захватывать буквы, только цифры, пробелы, дроби и "to"
        pattern = r'^([\d\s/.,]+(?:\s+to\s+[\d\s/.,]+)?)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp|tsp|pounds?|ounces?|lbs?|lb|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Обработка диапазонов типа "6 to 7" или "1/4 to 1/2"
            if ' to ' in amount_str or '-' in amount_str:
                amount = amount_str  # Оставляем как есть
            # Обработка дробей типа "1/2" или "2 1/2"
            elif '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            # Если не удалось преобразовать, возвращаем как есть
                            amount = amount_str
                            break
                else:
                    amount = total
            else:
                try:
                    # Попытка преобразовать в число
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for topping|for serving)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовки с "Ingredients" или "Ingredient"
        ingredient_header = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text(strip=True)
            # Ищем заголовки типа "Ingredients You'll Need", "Main Ingredients"
            if re.search(r'\bingredients?\b.*need|main\s+ingredients?', heading_text, re.IGNORECASE):
                ingredient_header = heading
                break
        
        # Если не нашли, ищем просто "Ingredients"
        if not ingredient_header:
            for heading in self.soup.find_all(['h2', 'h3', 'h4']):
                heading_text = heading.get_text(strip=True)
                if re.match(r'^ingredients?:?$', heading_text, re.IGNORECASE):
                    ingredient_header = heading
                    break
        
        if ingredient_header:
            # Теперь ищем все h4 заголовки после этого заголовка, которые начинаются с "For the"
            # или являются подсекциями ингредиентов
            next_elem = ingredient_header.find_next_sibling()
            
            while next_elem:
                # Останавливаемся на следующем крупном заголовке h2 или h3
                if next_elem.name in ['h2', 'h3']:
                    # Проверяем, не является ли это заголовком с инструкциями
                    next_text = next_elem.get_text(strip=True)
                    if re.search(r'instructions?|directions?|steps?|how to', next_text, re.IGNORECASE):
                        break
                    # Если это другой заголовок ингредиентов, продолжаем
                    if not re.search(r'ingredients?', next_text, re.IGNORECASE):
                        break
                
                # Если это h4 заголовок подсекции (например, "For the Crust:")
                if next_elem.name == 'h4':
                    h4_text = next_elem.get_text(strip=True)
                    # Проверяем, является ли это подсекцией ингредиентов
                    if h4_text.startswith('For the') or (h4_text.endswith(':') and not re.match(r'^\d+\.', h4_text)):
                        # Извлекаем следующий ul после этого h4
                        ul = next_elem.find_next_sibling('ul')
                        if ul:
                            items = ul.find_all('li', recursive=False)
                            for item in items:
                                ingredient_text = item.get_text(separator=' ', strip=True)
                                if ingredient_text and len(ingredient_text) < 200:
                                    parsed = self.parse_ingredient_item(ingredient_text)
                                    if parsed and parsed.get('name'):
                                        ingredients.append(parsed)
                
                # Если это просто ul сразу после заголовка ингредиентов
                if next_elem.name == 'ul' and not ingredients:
                    items = next_elem.find_all('li', recursive=False)
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        if ingredient_text and len(ingredient_text) < 200:
                            parsed = self.parse_ingredient_item(ingredient_text)
                            if parsed and parsed.get('name'):
                                ingredients.append(parsed)
                
                next_elem = next_elem.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все заголовки h3 и h4, которые содержат номера шагов
        # и следующие за ними параграфы
        all_headings = self.soup.find_all(['h3', 'h4'])
        
        for heading in all_headings:
            heading_text = heading.get_text(strip=True)
            
            # Проверяем, начинается ли заголовок с номера (например, "1. Prepare...")
            if re.match(r'^\d+\.', heading_text):
                # Извлекаем текст после номера
                step_text = re.sub(r'^\d+\.\s*', '', heading_text)
                
                # Ищем следующие параграфы после заголовка
                next_elem = heading.find_next_sibling()
                paragraphs = []
                
                while next_elem and next_elem.name == 'p':
                    p_text = next_elem.get_text(separator=' ', strip=True)
                    if p_text:
                        paragraphs.append(p_text)
                    next_elem = next_elem.find_next_sibling()
                
                # Объединяем заголовок и параграфы
                if paragraphs:
                    full_step = step_text + ' ' + ' '.join(paragraphs)
                else:
                    full_step = step_text
                
                full_step = self.clean_text(full_step)
                if full_step:
                    steps.append(full_step)
        
        # Если не нашли пронумерованные заголовки, пробуем другой подход
        # Ищем все параграфы после заголовка "Instructions" или "Directions"
        if not steps:
            instructions_header = None
            for h in self.soup.find_all(['h2', 'h3', 'h4']):
                if re.search(r'instructions|directions|steps', h.get_text(), re.IGNORECASE):
                    instructions_header = h
                    break
            
            if instructions_header:
                next_elem = instructions_header.find_next_sibling()
                while next_elem:
                    if next_elem.name in ['h2', 'h3', 'h4']:
                        # Остановиться на следующем заголовке
                        break
                    if next_elem.name == 'p':
                        p_text = next_elem.get_text(separator=' ', strip=True)
                        p_text = self.clean_text(p_text)
                        if p_text and len(p_text) > 10:
                            steps.append(p_text)
                    next_elem = next_elem.find_next_sibling()
        
        # Нумеруем шаги, если они еще не пронумерованы
        if steps:
            # Проверяем, начинается ли первый шаг с номера
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных articleSection
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Берем первую категорию
                                category = sections[0]
                                # Категории могут быть неправильные, используем контекст рецепта
                                # для определения правильной категории
                                return category
                            elif isinstance(sections, str):
                                return sections
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из хлебных крошек
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем текст с временем подготовки в параграфах
        for p in self.soup.find_all('p'):
            p_text = p.get_text()
            # Паттерн: "takes about 20 minutes to prep"
            match = re.search(r'(\d+)\s*minutes?\s+to\s+prep', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} minutes"
            
            # Паттерн: "Prep: 20 minutes" или "Prep Time: 20 minutes"
            match = re.search(r'Prep(?:\s+Time)?:\s*(\d+)\s*(minutes?|hours?)', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем текст с временем приготовления в параграфах
        for p in self.soup.find_all('p'):
            p_text = p.get_text()
            # Паттерн: "50-60 minutes to bake" или "1 hour to cook"
            match = re.search(r'(\d+(?:-\d+)?)\s*(minutes?|hours?)\s+to\s+(?:bake|cook)', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}"
            
            # Паттерн: "Cook: 50 minutes" или "Cook Time: 1 hour"
            match = re.search(r'Cook(?:\s+Time)?:\s*(\d+(?:-\d+)?)\s*(minutes?|hours?)', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}"
            
            # Паттерн: "Bake for 50-60 minutes"
            match = re.search(r'Bake\s+for\s+(\d+(?:-\d+)?)\s*(minutes?|hours?)', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем текст с общим временем в параграфах
        for p in self.soup.find_all('p'):
            p_text = p.get_text()
            # Паттерн: "let it cool for at least 2 hours" для общего времени
            # или "Total: 4 hours"
            match = re.search(r'Total(?:\s+Time)?:\s*(\d+)\s*(minutes?|hours?)', p_text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} {match.group(2)}"
            
            # Для этого сайта, общее время часто упоминается как время охлаждения
            match = re.search(r'(?:cool|chill|rest)\s+for\s+(?:at\s+least\s+)?(\d+)\s*(hours?)', p_text, re.IGNORECASE)
            if match:
                # Если нашли время охлаждения, это может быть частью общего времени
                cool_hours = int(match.group(1))
                
                # Пытаемся найти полное описание времени в том же параграфе
                full_match = re.search(r'takes\s+about\s+(\d+)\s*minutes?\s+to\s+prep.*?(\d+)\s*(?:hour|minute).*?chill.*?(\d+(?:-\d+)?)\s*minutes?\s+to\s+bake.*?(?:cool|chill)\s+for\s+(?:at\s+least\s+)?(\d+)\s*hours?', p_text, re.IGNORECASE)
                if full_match:
                    prep_min = int(full_match.group(1))
                    bake_min_str = full_match.group(3)
                    cool_hours_val = int(full_match.group(4))
                    
                    # Берем максимальное время для bake если это диапазон
                    if '-' in bake_min_str:
                        bake_min = int(bake_min_str.split('-')[1])
                    else:
                        bake_min = int(bake_min_str)
                    
                    # Вычисляем общее время
                    total_hours = cool_hours_val + (prep_min + bake_min + 60) // 60  # 60 для chill
                    return f"{total_hours} hours"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_list = []
        
        # Ищем FAQ секцию
        faq_section = self.soup.find('section', class_='fmp-faq')
        if faq_section:
            details = faq_section.find_all('details')
            for detail in details:
                # Извлекаем ответ из div с классом "a"
                answer_div = detail.find('div', class_='a')
                if answer_div:
                    answer_text = answer_div.get_text(separator=' ', strip=True)
                    answer_text = self.clean_text(answer_text)
                    if answer_text:
                        notes_list.append(answer_text)
        
        # Ищем секцию "Tips" или "Notes"
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text(strip=True)
            if re.search(r'tips|notes|cook.*note', heading_text, re.IGNORECASE):
                # Извлекаем следующие параграфы
                next_elem = heading.find_next_sibling()
                while next_elem and next_elem.name == 'p':
                    p_text = next_elem.get_text(separator=' ', strip=True)
                    p_text = self.clean_text(p_text)
                    if p_text and len(p_text) > 10:
                        notes_list.append(p_text)
                    next_elem = next_elem.find_next_sibling()
                break
        
        if notes_list:
            return ' '.join(notes_list)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Извлекаем ключевые слова из названия
        dish_name = self.extract_dish_name()
        if dish_name:
            # Убираем стоп-слова
            stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                        'of', 'with', 'by', 'from', 'recipe', 'irresistible', 'delicious'}
            words = dish_name.lower().split()
            keywords = [w for w in words if w not in stopwords and len(w) > 2]
            tags_list.extend(keywords)
        
        # Извлекаем категорию как тег (но не используем напрямую из JSON-LD, вместо этого определяем контекстно)
        # Определяем тип блюда по ключевым словам
        if dish_name:
            dish_lower = dish_name.lower()
            if any(word in dish_lower for word in ['pie', 'cake', 'cookie', 'brownie', 'tart']):
                if 'dessert' not in tags_list:
                    tags_list.append('dessert')
            elif any(word in dish_lower for word in ['chicken', 'beef', 'pork', 'fish', 'salmon']):
                tags_list.append('main course')
            elif any(word in dish_lower for word in ['oats', 'pancake', 'waffle', 'toast']):
                tags_list.append('breakfast')
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag not in seen and len(tag) > 1:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "happilyhomebaked_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(HappilyHomeBakedExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python happilyhomebaked_com.py")


if __name__ == "__main__":
    main()
