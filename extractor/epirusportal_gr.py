"""
Экстрактор данных рецептов для сайта epirusportal.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EpirusportalExtractor(BaseRecipeExtractor):
    """Экстрактор для epirusportal.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из title tag
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " | Απλές και νόστιμες συνταγές - Ειδήσεις Ηπείρου"
            title = re.split(r'\s*[|–-]\s*', title)[0]
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.split(r'\s*[|–-]\s*', title)[0]
            return self.clean_text(title)
        
        # Последняя попытка - h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем найти в начале контента (до секции ингредиентов)
        content_div = self.soup.find('div', class_='tdb_single_content')
        if not content_div:
            content_div = self.soup.find('div', class_='tdb-block-inner')
        
        if content_div:
            paragraphs = content_div.find_all('p')
            # Ищем первый параграф, который не является заголовком секции
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Пропускаем заголовки секций и пустые строки
                if text and 'Υλικά' not in text and 'ΕΚΤΕΛΕΣΗ' not in text and not text.startswith('•'):
                    # Проверяем, что это не слишком длинный текст (вероятно, это описание)
                    if len(text) < 500:
                        return self.clean_text(text)
                    break
        
        # Запасной вариант - ищем в meta description, но только начало
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc_text = meta_desc['content']
            # Обрезаем до "Υλικά" если есть
            if 'Υλικά' in desc_text:
                desc_text = desc_text.split('Υλικά')[0].strip()
            return self.clean_text(desc_text)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "• 1 κιλό φρέσκο πράσινο λουβί" или "50 γρ. βούτυρο"
            
        Returns:
            dict: {"name": "φρέσκο πράσινο λουβί", "amount": "1", "units": "κιλό"}
        """
        if not ingredient_text:
            return None
        
        # Убираем bullet point и чистим текст
        text = ingredient_text.replace('•', '').strip()
        text = self.clean_text(text)
        
        if not text:
            return None
        
        # Заменяем Unicode дроби на числа/строки
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества и единицы измерения
        # Примеры: "1 κιλό ...", "50 γρ. ...", "2 κ.σ. ..."
        # Важно: используем non-greedy match для единиц
        pattern = r'^([\d\s/.,]+)?\s*(κιλό|κιλά|γραμμάρια|γραμμάριο|γρ\.?|g|kg|ml|l|λίτρο|λίτρα|κουταλι[έά].*?|κουταλάκι.*?|κ\.γ\.|κ\.σ\.|φλιτζάνι|φλυτζάνι|pieces?|medium|tablespoons?|teaspoons?|grams?|piece|τεμάχιο|μεσαίου μεγέθους|πρέζα)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Паттерн для случаев без единиц: "1 κρεμμύδι", "2 φιλέτα Λαβράκι"
            pattern2 = r'^(\d+(?:[/.]\d+)?)\s+(.+)$'
            match2 = re.match(pattern2, text)
            if match2:
                amount_str, name = match2.groups()
                amount = amount_str  # Оставляем как строку
                units = None
            else:
                # Если паттерн не совпал, возвращаем только название
                return {
                    "name": text,
                    "amount": None,
                    "units": None
                }
        else:
            amount_str, units, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Оставляем как строку для дробей, преобразуем в число для целых
                if '/' in amount_str:
                    # Оставляем дробь как строку
                    amount = amount_str
                else:
                    try:
                        # Преобразуем в число
                        if '.' in amount_str or ',' in amount_str:
                            amount_str = amount_str.replace(',', '.')
                            amount = int(float(amount_str)) if float(amount_str).is_integer() else float(amount_str)
                        else:
                            amount = int(amount_str)
                    except ValueError:
                        amount = amount_str
            
            # Обработка единицы измерения
            units = units.strip() if units else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed" и греческие эквиваленты
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Удаляем "από τις...", "ψιλοκομμένο" и подобные описания в конце
        name = re.sub(r'\s+(από τις|ψιλοκομμένο|τριμμένο).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все параграфы в основном контенте
        content_div = self.soup.find('div', class_='tdb_single_content')
        if not content_div:
            content_div = self.soup.find('div', class_='tdb-block-inner')
        
        if not content_div:
            return None
        
        paragraphs = content_div.find_all('p')
        
        # Вариант 1: Ингредиенты с bullet points
        found_bullets = False
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем, является ли это заголовком секции ингредиентов
            if text.upper() == 'ΥΛΙΚΑ' or text.upper() == 'ΥΛΙΚΆ' or 'Υλικά' in text:
                found_bullets = True
                continue
            
            # Проверяем, не начинается ли следующая секция (инструкции)
            if found_bullets and ('ΕΚΤΕΛΕ' in text.upper()):
                break
            
            # Если мы в секции ингредиентов и строка начинается с bullet point
            if found_bullets and text.startswith('•'):
                parsed = self.parse_ingredient(text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если нашли ингредиенты с bullets, возвращаем
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        # Вариант 2: Ингредиенты разделены <br/> тегами
        for p in paragraphs:
            # Проверяем, содержит ли параграф "Υλικά"
            if 'Υλικά' in p.get_text():
                # Получаем содержимое параграфа, разделенное по <br/>
                # Заменяем <br/> на специальный маркер и разбиваем
                html_content = str(p)
                
                # Разбираем структуру с <br/>
                for content in p.stripped_strings:
                    # Пропускаем заголовки и пустые строки
                    if not content or 'Υλικά' in content or content.startswith('Для'):
                        continue
                    if 'Για τη' in content and ':' in content:  # Подзаголовок секции
                        continue
                    
                    # Пробуем распарсить как ингредиент
                    parsed = self.parse_ingredient(content)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
                
                # Также проверяем следующий параграф (может быть продолжение)
                idx = paragraphs.index(p)
                if idx + 1 < len(paragraphs):
                    next_p = paragraphs[idx + 1]
                    next_text = next_p.get_text(strip=True)
                    # Проверяем, не является ли это началом инструкций
                    if 'ΕΚΤΕΛΕ' not in next_text.upper():
                        for content in next_p.stripped_strings:
                            if not content or content.startswith('Для'):
                                continue
                            if 'Για τη' in content and ':' in content:
                                continue
                            
                            parsed = self.parse_ingredient(content)
                            if parsed and parsed.get('name'):
                                ingredients.append(parsed)
                
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем все параграфы в основном контенте
        content_div = self.soup.find('div', class_='tdb_single_content')
        if not content_div:
            content_div = self.soup.find('div', class_='tdb-block-inner')
        
        if not content_div:
            return None
        
        # Находим секцию с инструкциями
        # Ищем заголовок "ΕΚΤΕΛΕΣΗ" (Execution/Instructions)
        found_instructions_section = False
        paragraphs = content_div.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем, является ли это заголовком секции инструкций
            if text.upper() == 'ΕΚΤΕΛΕΣΗ' or text.upper() == 'ΕΚΤΕΛΕΣΗ' or 'ΕΚΤΕΛΕ' in text.upper():
                found_instructions_section = True
                continue
            
            # Если мы в секции инструкций и строка не пустая и не начинается с bullet
            if found_instructions_section and text and not text.startswith('•'):
                # Проверяем, не является ли это началом новой секции
                if text.upper() in ['ΥΛΙΚΑ', 'ΥΛΙΚΆ', 'NOTES', 'ΣΗΜΕΙΩΣΕΙΣ']:
                    break
                
                # Очищаем текст
                cleaned = self.clean_text(text)
                if cleaned and len(cleaned) > 10:  # Игнорируем очень короткие строки
                    instructions.append(cleaned)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем в JSON-LD, если есть breadcrumbs или category
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем различные варианты структуры
                if isinstance(data, dict):
                    # Ищем articleSection
                    if 'articleSection' in data:
                        return self.clean_text(data['articleSection'])
                    
                    # Ищем в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'articleSection' in item:
                                return self.clean_text(item['articleSection'])
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте epirusportal.gr времена обычно не указаны
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем найти упоминания времени в инструкциях
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени типа "40 λεπτά", "5 minutes", "1 ώρα"
            time_patterns = [
                r'(\d+)\s*(λεπτ[άα]|minutes?|mins?)',
                r'(\d+)\s*(ώρ[εα]|hours?|hrs?)',
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, instructions, re.IGNORECASE)
                if match:
                    number = match.group(1)
                    unit = match.group(2)
                    
                    # Нормализуем единицу
                    if 'λεπτ' in unit.lower() or 'minute' in unit.lower() or 'min' in unit.lower():
                        return f"{number} minutes"
                    elif 'ώρ' in unit.lower() or 'hour' in unit.lower() or 'hr' in unit.lower():
                        return f"{number} hours"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте epirusportal.gr общее время обычно не указано отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На сайте epirusportal.gr заметки обычно не выделены отдельно
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в метаданных
        tags = []
        
        # Проверяем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
        
        # Проверяем article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag_meta in article_tags:
            if tag_meta.get('content'):
                tags.append(tag_meta['content'].strip())
        
        # Фильтруем и возвращаем
        if tags:
            # Убираем дубликаты
            unique_tags = []
            seen = set()
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем различные варианты структуры
                if isinstance(data, dict):
                    # Прямое изображение
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, dict) and 'url' in img:
                            urls.append(img['url'])
                        elif isinstance(img, list):
                            for i in img:
                                if isinstance(i, str):
                                    urls.append(i)
                                elif isinstance(i, dict) and 'url' in i:
                                    urls.append(i['url'])
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'image' in item:
                                img = item['image']
                                if isinstance(img, str):
                                    urls.append(img)
                                elif isinstance(img, dict) and 'url' in img:
                                    urls.append(img['url'])
                                    
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
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки HTML файлов сайта epirusportal.gr"""
    # Ищем директорию с HTML-страницами
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "epirusportal_gr"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(EpirusportalExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Создайте директорию preprocessed/epirusportal_gr с HTML файлами")


if __name__ == "__main__":
    main()
