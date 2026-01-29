"""
Экстрактор данных рецептов для сайта domacikolaci.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DomacikolaciNetExtractor(BaseRecipeExtractor):
    """Экстрактор для domacikolaci.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем найти в секциях "Sastojci:" или "Priprema:"
        # Там часто указано точное название в именительном падеже
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            paragraphs = entry_content.find_all('p')
            for p in paragraphs:
                p_text = self.clean_text(p.get_text())
                # Ищем паттерн "[Название] – sastojci:" или "[Название] – priprema:"
                match = re.match(r'^(.+?)\s*[-–]\s*(sastojci|priprema)\s*:?\s*$', p_text, re.IGNORECASE)
                if match:
                    dish_name = match.group(1).strip()
                    return dish_name
        
        # Ищем в заголовке h1 с классом entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем префиксы типа "Grickalica bez konkurencije: Isprobajte recept za"
            # и оставляем только название блюда
            # Паттерн: ищем текст после двоеточия или после "recept za"
            if ':' in title:
                # Берем часть после двоеточия
                parts = title.split(':')
                if len(parts) > 1:
                    after_colon = parts[-1].strip()
                    # Если там есть "recept za", берем что после него
                    if 'recept za' in after_colon.lower():
                        match = re.search(r'recept za\s+(.+)', after_colon, re.IGNORECASE)
                        if match:
                            result = match.group(1).strip()
                            # Убираем возможные суффиксы "koje bismo jeli..." и другие описательные фразы
                            result = re.sub(r'\s+koje\s+.*$', '', result, flags=re.IGNORECASE)
                            result = re.sub(r'\s*[-–]\s*.*$', '', result)
                            return result
                    return after_colon
            
            # Если нет двоеточия, ищем "recept za"
            if 'recept za' in title.lower():
                match = re.search(r'recept za\s+(.+)', title, re.IGNORECASE)
                if match:
                    result = match.group(1).strip()
                    # Убираем возможные суффиксы "koje bismo jeli..."
                    result = re.sub(r'\s+koje\s+.*$', '', result, flags=re.IGNORECASE)
                    result = re.sub(r'\s*[-–]\s*.*$', '', result)
                    return result
            
            # Если это название с "Ovo je najbolji recept za...", извлекаем название блюда
            if 'ovo je' in title.lower() and 'recept za' in title.lower():
                match = re.search(r'recept za\s+([^–\-]+)', title, re.IGNORECASE)
                if match:
                    result = match.group(1).strip()
                    # Убираем "– Samo N sastojka" и подобное
                    result = re.sub(r'\s*[-–]\s*.*$', '', result)
                    return result
            
            return title
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Убираем суффиксы сайта
            title = re.sub(r'\s*[-–]\s*Domaći kolači.*$', '', title, flags=re.IGNORECASE)
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта
        
        Note: В HTML нет явного описания в meta тегах.
        Пытаемся составить описание из названия блюда и контекста.
        """
        # Проверяем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc and len(desc) > 10:
                return desc
        
        # Пытаемся найти первый параграф в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем первый параграф, который не является заголовком секции
            for p in entry_content.find_all('p'):
                text = self.clean_text(p.get_text())
                # Пропускаем секционные заголовки
                if text and not text.endswith(':') and len(text) > 20:
                    # Пропускаем параграфы с ингредиентами (содержат <br>)
                    if not p.find('br'):
                        return text
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем параграф с заголовком "Sastojci:" и следующий за ним параграф с <br>
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Флаг, указывающий, что мы нашли секцию ингредиентов
        found_sastojci = False
        
        for i, p in enumerate(paragraphs):
            p_text = self.clean_text(p.get_text())
            
            # Проверяем, является ли это заголовком секции ингредиентов
            if re.match(r'^sastojci\s*:?\s*$', p_text, re.IGNORECASE):
                found_sastojci = True
                continue
            
            # Если мы нашли секцию ингредиентов или если параграф содержит <br> и похож на ингредиенты
            if found_sastojci or (p.find('br') and self._looks_like_ingredients(p_text)):
                # Проверяем, содержит ли параграф <br> теги
                if p.find('br'):
                    # Извлекаем каждую строку между <br>
                    # Используем str() вместо decode_contents() и split по <br/> и <br>
                    html_content = str(p)
                    # Заменяем различные варианты br на единый разделитель
                    html_content = re.sub(r'<br\s*/?>', '|||SPLIT|||', html_content)
                    lines = html_content.split('|||SPLIT|||')
                    
                    for line in lines:
                        # Очищаем от HTML тегов
                        from bs4 import BeautifulSoup
                        clean_line = BeautifulSoup(line, 'lxml').get_text()
                        clean_line = self.clean_text(clean_line)
                        
                        if clean_line:
                            # Пропускаем строки, которые явно являются инструкциями
                            if self._looks_like_instruction(clean_line):
                                # Если встретили инструкцию, прекращаем парсинг ингредиентов
                                found_sastojci = False
                                break
                            
                            parsed = self.parse_ingredient(clean_line)
                            if parsed:
                                ingredients.append(parsed)
                    
                    # Если нашли ингредиенты, выходим
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _looks_like_ingredients(self, text: str) -> bool:
        """Проверяет, похож ли текст на список ингредиентов"""
        # Ингредиенты обычно содержат единицы измерения
        units_pattern = r'\b(ml|grama?|gram|kg|l|kom?|kašik|kašičica|srednje?|velike?|male?)\b'
        return bool(re.search(units_pattern, text, re.IGNORECASE))
    
    def _looks_like_instruction(self, text: str) -> bool:
        """Проверяет, похож ли текст на инструкцию приготовления"""
        # Инструкции обычно содержат глаголы действия
        instruction_keywords = r'\b(operite|ogulite|naribajte|dodajte|pomiješajte|zagrijte|pržite|pecite|iseći|ostavite|narežite|umočite|stavite|poslužite)\b'
        return bool(re.search(instruction_keywords, text, re.IGNORECASE))
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 ml šlaga" или "2 srednje tikvice"
            
        Returns:
            dict: {"name": "šlag", "amount": "500", "unit": "ml"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 ml šlaga", "2 srednje tikvice", "300 g glatkog brašna"
        # Паттерн должен учитывать различные единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(ml|grama?|gram|grams?|kg|l|srednje?|velike?|male?|kom?|kašik|kašičica|g)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            # Но пропускаем пустые или слишком короткие строки
            if len(text) < 2:
                return None
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
            # Обработка дробей (если есть)
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Возвращаем как int если целое число
                amount = int(total) if total.is_integer() else total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount_val = float(amount_str)
                    # Возвращаем как int если целое число, иначе float
                    amount = int(amount_val) if amount_val.is_integer() else amount_val
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip().lower()
            # Нормализация единиц
            unit_map = {
                'gram': 'grams',
                'grama': 'grams',
                'g': 'g',
                'srednje': 'srednje',
                'velike': 'srednje velike',
                'male': 'srednje',
                'kom': None,
            }
            # Применяем маппинг если есть
            # Но для domacikolaci оставляем оригинальные единицы
            units = unit
        else:
            units = None
        
        # Очистка названия
        name = name.strip()
        # Удаляем фразы "za prženje", "po želji"
        name = re.sub(r'\b(za prženje|po želji|ili)\b.*$', '', name, flags=re.IGNORECASE)
        
        # Нормализуем родительный падеж в сербском/хорватском
        # Преобразуем из родительного падежа в именительный
        # "kremastog sira" -> "kremasti sir"
        # "glatkog brašna" -> "glatko brašno"
        # "kondenzovanog mleka" -> "kondenzovano mleko"
        
        # Множественное число:  
        # "krušnih mrvica" -> "krušne mrvice"
        # "jagoda" -> "jagode"
        
        # Сложная грамматика, используем простые правила:
        # 1. Прилагательное мужского рода: -og -> -i
        # 2. Прилагательное среднего рода: -og -> -o
        # 3. Прилагательное множественного числа: -ih -> -e
        # 4. Существительное мужского рода: убираем окончание -a (sira -> sir)
        # 5. Существительное среднего рода: -a -> -o (brašna -> brašno, mleka -> mleko)
        
        # Применяем правила к двухсловным фразам (прилагательное + существительное)
        words = name.split()
        
        if len(words) == 2:
            adj, noun = words
            # Проверяем окончания прилагательного
            if adj.endswith('og'):
                # Мужской или средний род - нужно проверить существительное
                if noun.endswith('a'):
                    # Если существительное на -a, это родительный падеж
                    # Определяем род по окончанию существительного без -a
                    noun_base = noun[:-1]
                    # Проверяем характерные окончания для определения рода
                    # Средний род обычно: -no, -ko, -to, -vo
                    # Мужской род обычно: согласная
                    if noun_base.endswith(('n', 'k', 't', 'v', 'c')):
                        # Скорее всего средний род: brašno, mleko, jelo, pecivo
                        adj = adj[:-2] + 'o'
                        noun = noun_base + 'o'
                    else:
                        # Мужской род: sir, šećer
                        adj = adj[:-2] + 'i'
                        noun = noun_base
                    name = f"{adj} {noun}"
            elif adj.endswith('ih'):
                # Множественное число
                # krušnih mrvica -> krušne mrvice
                adj = adj[:-2] + 'e'
                if noun.endswith('a'):
                    noun = noun[:-1] + 'e'
                name = f"{adj} {noun}"
        elif len(words) == 1:
            # Одно слово - вероятно существительное в родительном падеже
            word = words[0]
            if word.endswith('aga'):
                # šlaga -> šlag
                name = word[:-1]
            elif word.endswith('eka'):
                # mleka -> mleko
                name = word[:-1] + 'o'
            elif word.endswith('e'):
                # Возможно множественное число - оставляем как есть
                pass
        
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        # Lowercase the first letter to match reference format
        name = name[0].lower() + name[1:] if len(name) > 1 else name.lower()
        
        # Return with keys in the same order as reference: name, units, amount
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления (instructions)"""
        instructions = []
        
        # Ищем параграф с заголовком "Priprema:" и следующие за ним параграфы
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Флаг, указывающий, что мы нашли секцию приготовления
        found_priprema = False
        
        for p in paragraphs:
            p_text = self.clean_text(p.get_text())
            
            # Проверяем, является ли это заголовком секции приготовления
            if re.match(r'^priprema\s*:?\s*$', p_text, re.IGNORECASE):
                found_priprema = True
                continue
            
            # Если мы нашли секцию приготовления
            if found_priprema:
                # Если параграф содержит <br> теги, разбиваем на шаги
                if p.find('br'):
                    html_content = str(p)
                    html_content = re.sub(r'<br\s*/?>', '|||SPLIT|||', html_content)
                    lines = html_content.split('|||SPLIT|||')
                    
                    for line in lines:
                        from bs4 import BeautifulSoup
                        clean_line = BeautifulSoup(line, 'lxml').get_text()
                        clean_line = self.clean_text(clean_line)
                        if clean_line and len(clean_line) > 10:
                            instructions.append(clean_line)
                else:
                    # Обычный параграф - это один шаг
                    if p_text and len(p_text) > 10:
                        # Проверяем, не является ли это заголовком следующей секции
                        if p_text.endswith(':') or p_text.startswith('Napomena') or p_text.startswith('Savjet'):
                            # Прекращаем сбор инструкций
                            break
                        instructions.append(p_text)
        
        # Если не нашли через "Priprema:", ищем параграфы с инструкциями
        # (те, которые содержат глаголы действия и не являются ингредиентами)
        if not instructions:
            for p in paragraphs:
                p_text = self.clean_text(p.get_text())
                # Пропускаем заголовки секций
                if p_text.endswith(':'):
                    continue
                # Пропускаем ингредиенты
                if p.find('br') and self._looks_like_ingredients(p_text):
                    continue
                # Если выглядит как инструкция
                if self._looks_like_instruction(p_text) and len(p_text) > 20:
                    instructions.append(p_text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем в meta тегах или в breadcrumbs
        # Проверяем span с классом entry-meta-categories
        category_span = self.soup.find('span', class_='entry-meta-categories')
        if category_span:
            links = category_span.find_all('a')
            if links:
                categories = [self.clean_text(link.get_text()) for link in links]
                # Фильтруем общие категории вроде "kuhinja"
                filtered = [c for c in categories if c.lower() not in ['kuhinja', 'blog']]
                if filtered:
                    return filtered[0]
                elif categories:
                    return categories[0]
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки
        
        Note: В HTML нет структурированной информации о времени.
        Возвращаем None.
        """
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления
        
        Note: В HTML нет структурированной информации о времени.
        Пытаемся найти упоминания в тексте инструкций.
        """
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени: "nekoliko minuta", "2 sata", etc.
            time_pattern = r'(\d+\s*(sata?|minuta?|hours?|minutes?))'
            match = re.search(time_pattern, instructions, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # Пытаемся найти в инструкциях
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени
            time_pattern = r'(\d+\s*(sata?|hours?))'
            match = re.search(time_pattern, instructions, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                # Преобразуем в стандартный формат
                if 'sata' in time_str or 'hours' in time_str:
                    return time_str.replace('sata', 'hours').replace('sat', 'hours')
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # Ищем параграфы, которые идут после инструкций
        # и содержат ключевые слова "Napomena", "Savjet", "Tako", etc.
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        for p in paragraphs:
            p_text = self.clean_text(p.get_text())
            # Ищем параграфы, которые начинаются с ключевых слов
            if re.match(r'^(Napomena|Savjet|Tako|Detalje)', p_text, re.IGNORECASE):
                return p_text
            # Или содержат указания на альтернативные методы
            if 'friteza' in p_text.lower() or 'alternativ' in p_text.lower():
                return p_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта
        
        Note: В HTML нет явных тегов.
        Возвращаем None.
        """
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем изображения в контенте статьи
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img')
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты
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
        dish_name = self.extract_dish_name()
        # Capitalize first letter to match reference format
        if dish_name:
            dish_name = dish_name[0].upper() + dish_name[1:] if len(dish_name) > 1 else dish_name.upper()
        
        return {
            "dish_name": dish_name,
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
    """Точка входа для обработки HTML файлов из preprocessed/domacikolaci_net"""
    import os
    
    # Определяем путь к директории с HTML файлами
    # Путь относительно корня репозитория
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "domacikolaci_net"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка файлов из: {recipes_dir}")
        process_directory(DomacikolaciNetExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python domacikolaci_net.py")


if __name__ == "__main__":
    main()
