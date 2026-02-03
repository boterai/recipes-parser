"""
Экстрактор данных рецептов для сайта ristoranteilgranduca.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RistoranteilgranducaExtractor(BaseRecipeExtractor):
    """Экстрактор для ristoranteilgranduca.it"""
    
    @staticmethod
    def clean_text_italian(text: str) -> str:
        """Очистка текста от нечитаемых символов и нормализация (итальянская версия)"""
        if not text:
            return text
        
        # Декодируем HTML entities
        import html as html_module
        text = html_module.unescape(text)
        
        # Заменяем Unicode символы разделителей
        text = text.replace('‚', ',').replace('⁚', ':')
        
        # Удаляем Unicode символы типа ▢, □, ✓ и другие специальные символы
        text = re.sub(r'[▢□✓✔▪▫●○■]', '', text)
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        # Убираем пробелы в начале и конце
        text = text.strip()
        return text
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Убираем суффиксы типа " – Ristorante Gran Duca"
            title = re.sub(r'\s+[–-]\s+.*$', '', title)
            # Берем часть до двоеточия как название
            if ':' in title:
                parts = title.split(':', 1)
                title = parts[0].strip()
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем параграф с текстом "è una ricetta semplice" - это обычно описание
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            text = self.clean_text_italian(text)
            # Ищем предложение, которое начинается с описания блюда
            if re.search(r'è\s+una\s+ricetta\s+semplice', text, re.I):
                # Берем первое предложение
                sentences = re.split(r'[.!?]\s+', text)
                if sentences and len(sentences) > 0:
                    desc = sentences[0]
                    if not desc.endswith('.'):
                        desc += '.'
                    return desc
        
        # Fallback: создаем описание из названия блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            return f"Una ricetta semplice e gustosa di {dish_name.lower()}."
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Ingredienti Necessari" или "Ingredienti" в h2 или h3
        ingredients_section = None
        for tag in ['h2', 'h3']:
            headers = self.soup.find_all(tag)
            for header in headers:
                header_text = header.get_text(strip=True)
                if re.search(r'Ingredienti', header_text, re.I):
                    ingredients_section = header
                    break
            if ingredients_section:
                break
        
        if ingredients_section:
            # Сначала проверяем, есть ли список <ul> после заголовка
            next_ul = ingredients_section.find_next('ul')
            
            # Проверяем, что ul находится близко к заголовку (не дальше 2 элементов)
            if next_ul:
                # Извлекаем все <li> элементы из всех <ul> блоков, пока не встретим следующий заголовок
                current = ingredients_section.find_next_sibling()
                while current:
                    # Останавливаемся на следующем заголовке
                    if current.name in ['h2', 'h3', 'h4']:
                        break
                    
                    # Если это ul, обрабатываем его элементы
                    if current.name == 'ul':
                        for li in current.find_all('li'):
                            ingredient_text = li.get_text(strip=True)
                            ingredient_text = self.clean_text_italian(ingredient_text)
                            if ingredient_text:
                                parsed = self.parse_ingredient_italian(ingredient_text)
                                if parsed and parsed.get('name') and len(parsed.get('name', '')) > 1:
                                    ingredients.append(parsed)
                    # Если это параграф с "Per", может быть группа ингредиентов
                    elif current.name == 'p':
                        p_text = current.get_text(strip=True)
                        # Пропускаем пустые параграфы и те, что не начинаются с "Per"
                        if p_text and re.match(r'^Per\s+', p_text, re.I):
                            # Это может быть заголовок группы, продолжаем
                            pass
                    
                    current = current.find_next_sibling()
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
            
            # Если нет списка, ищем параграф с текстом
            next_p = ingredients_section.find_next('p')
            if next_p:
                text = next_p.get_text(strip=True)
                text = self.clean_text_italian(text)
                
                # Разбиваем по группам "Per la scarola:", "Per la pasta sfoglia:", etc.
                # Сначала разделяем по точке с запятой и точке перед "Per"
                groups = re.split(r'[;.]\s*(?=Per\s+)', text, flags=re.I)
                
                for group in groups:
                    group = group.strip()
                    if not group:
                        continue
                    
                    # Убираем префикс группы "Per la scarola:"
                    group = re.sub(r'^Per\s+(la|il|lo|i|le|gli)\s+[^:]+:\s*', '', group, flags=re.I)
                    
                    # Разделяем ингредиенты по запятым
                    ing_parts = group.split(',')
                    
                    for part in ing_parts:
                        part = part.strip()
                        if not part or part.endswith('.'):
                            part = part.rstrip('.')
                        if not part:
                            continue
                        
                        # Специальная обработка для "sale e pepe"
                        if re.match(r'^sale\s+(e|o)\s+pepe', part, re.I):
                            ingredients.append({"name": "sale", "amount": None, "units": None})
                            ingredients.append({"name": "pepe", "amount": None, "units": None})
                            continue
                        
                        # Парсим каждый ингредиент
                        parsed = self.parse_ingredient_italian(part)
                        if parsed and parsed.get('name') and len(parsed.get('name', '')) > 1:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_italian(self, text: str) -> Optional[dict]:
        """
        Парсинг итальянского ингредиента
        
        Args:
            text: Строка вида "1 cespo di scarola" или "2 cucchiai di olio" или "1 uovo sbattuto"
            
        Returns:
            dict: {"name": "scarola", "amount": 1, "units": "cespo"} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text_italian(text).lower()
        
        # Специальная обработка для "sale e pepe"
        if re.match(r'^sale\s+(e|o)\s+pepe', text, re.I):
            return {
                "name": "sale",
                "amount": None,
                "units": None
            }
        
        # Паттерн: "1 cespo di scarola" или "100g di parmigiano" или "1 spicchio d'aglio"
        # Для "d'aglio" обрабатываем отдельно
        pattern_dapostrophe = r'^([\d.,/]+)\s+([a-zàèéìòù]+)\s+d\'(.+)$'
        match = re.match(pattern_dapostrophe, text, re.I)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    if '/' in amount_str:
                        parts = amount_str.split('/')
                        amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = None
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": unit.strip() if unit else None
            }
        
        # Паттерн: "1 cespo di scarola" или "100g di parmigiano"
        # Группы: (количество) (единица) di (название)
        pattern_with_di = r'^([\d.,/]+)\s*([a-zàèéìòù]+)?\s+di\s+(.+)$'
        match = re.match(pattern_with_di, text, re.I)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    if '/' in amount_str:
                        parts = amount_str.split('/')
                        amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = None
            
            # Очистка названия - убираем "d'" в начале если есть
            name = name.strip()
            
            # Очистка названия от других артефактов
            name = re.sub(r'\s*\(.*?\)\s*', '', name)  # Убираем скобки
            name = re.sub(r'\s+', ' ', name).strip()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.strip() if unit else None
            }
        
        # Паттерн для "1 uovo sbattuto" или "1 rotolo di pasta sfoglia rettangolare"
        # Здесь "sbattuto" - это состояние (unit), а "uovo" - название
        # Группы: (количество) (название) (состояние/описание)
        pattern_with_adjective = r'^([\d.,/]+)\s+([a-zàèéìòù]+)\s+(sbattuto|tritato|grattugiato|macinato|tagliato|affettato)(.*)$'
        match = re.match(pattern_with_adjective, text, re.I)
        
        if match:
            amount_str, name, state, rest = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    if '/' in amount_str:
                        parts = amount_str.split('/')
                        amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = None
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": state.strip() if state else None
            }
        
        # Паттерн без "di": "sale e pepe q.b" или другие простые названия
        pattern_simple = r'^([\d.,/]+)?\s*([a-zàèéìòù]+)?\s*(.+)$'
        match = re.match(pattern_simple, text, re.I)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Проверяем, не является ли это просто названием без количества
            if not amount_str:
                # Если нет количества и "unit" не является известной единицей измерения,
                # то это просто название
                known_units = ['g', 'kg', 'ml', 'l', 'cucchiai', 'cucchiaio', 'cucchiaini', 'cucchiaino',
                              'tazza', 'tazze', 'bicchiere', 'bicchieri', 'pizzico', 'rametto', 'spicchio',
                              'foglio', 'fogli', 'cespo', 'rotolo', 'uovo', 'sbattuto', 'tritato']
                
                if not unit or unit.lower() not in known_units:
                    # Это просто название (весь текст)
                    name = text
                    # Убираем "q.b" и подобные пометки
                    name = re.sub(r'\s*q\.b\.?\s*$', '', name, flags=re.I)
                    # Убираем "a piacere"
                    name = re.sub(r'\s+a\s+piacere\s*$', '', name, flags=re.I)
                    name = name.strip()
                    # Пропускаем пустые названия и слишком длинные строки
                    if not name or len(name) < 2 or len(name) > 60:
                        return None
                    return {
                        "name": name,
                        "amount": None,
                        "units": None
                    }
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip().replace(',', '.')
                try:
                    if '/' in amount_str:
                        parts = amount_str.split('/')
                        amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = None
            
            # Очистка названия
            name = re.sub(r'\s*\(.*?\)\s*', '', name)
            name = re.sub(r'\s*q\.b\.?\s*$', '', name, flags=re.I)
            # Убираем описания типа "per spennellare"
            name = re.sub(r'\s+per\s+.*$', '', name, flags=re.I)
            # Убираем "a piacere"
            name = re.sub(r'\s+a\s+piacere\s*$', '', name, flags=re.I)
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Пропускаем пустые названия и слишком длинные строки
            if not name or len(name) < 2 or len(name) > 60:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.strip() if unit else None
            }
        
        # Если не совпадает ни один паттерн, возвращаем только название
        return {
            "name": text if len(text) <= 50 else None,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Создаем краткое резюме основных шагов из разных секций
        steps = []
        
        # Ищем все параграфы между заголовками h2 и h3, которые описывают процесс приготовления
        all_headers = self.soup.find_all(['h2', 'h3'])
        
        for header in all_headers:
            header_text = header.get_text(strip=True)
            # Пропускаем секцию с ингредиентами
            if re.search(r'Ingredienti', header_text, re.I):
                continue
            
            # Ищем секции приготовления
            if re.search(r'Preparazione|Cottura|Assemblaggio', header_text, re.I):
                # Берем параграф после заголовка
                next_p = header.find_next('p')
                if next_p:
                    step_text = next_p.get_text(separator=' ', strip=True)
                    step_text = self.clean_text_italian(step_text)
                    # Извлекаем ключевые действия из длинного текста
                    # Берем первое предложение как краткое резюме
                    sentences = re.split(r'[.!?]\s+', step_text)
                    if sentences:
                        # Берем первое предложение
                        summary = sentences[0]
                        if summary and len(summary) > 10:
                            steps.append(summary)
        
        if steps:
            # Нумеруем шаги
            numbered_steps = []
            for idx, step in enumerate(steps, 1):
                numbered_steps.append(f"{idx}. {step}")
            return '. '.join(numbered_steps) + '.'
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Определяем по ключевым словам в названии
        dish_name = self.extract_dish_name()
        
        if not dish_name:
            return "Main Course"
        
        dish_lower = dish_name.lower()
        
        # Десерты и сладости - должны иметь слово torta, dolce, etc в названии
        dessert_keywords = ['torta', 'dolce', 'dessert', 'ciambella', 'biscotti', 'gelato', 'tiramisù']
        if any(word in dish_lower for word in dessert_keywords):
            return "Dessert"
        
        # Антипасто
        if any(word in dish_lower for word in ['antipasto', 'bruschetta', 'crostini']):
            return "Antipasto"
        
        # По умолчанию - основное блюдо
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте упоминания времени подготовки
        text = self.soup.get_text()
        
        # Паттерны для времени подготовки
        patterns = [
            r'tempo\s+di\s+preparazione[:\s]+(\d+)\s*min',
            r'preparazione[:\s]+(\d+)\s*min',
            r'prep\s+time[:\s]+(\d+)\s*min',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминания времени приготовления
        text = self.soup.get_text()
        
        # Паттерны для времени приготовления
        patterns = [
            r'tempo\s+di\s+cottura[:\s]+(\d+)\s*min',
            r'cottura[:\s]+(\d+)\s*min',
            r'cook\s+time[:\s]+(\d+)\s*min',
            r'(\d+)-(\d+)\s*minuti',  # Диапазон типа "25-30 minuti"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                if len(match.groups()) > 1:
                    # Диапазон - берем верхнюю границу
                    minutes = match.group(2)
                else:
                    minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте упоминания общего времени
        text = self.soup.get_text()
        
        # Паттерны для общего времени
        patterns = [
            r'tempo\s+totale[:\s]+(\d+)\s*min',
            r'total\s+time[:\s]+(\d+)\s*min',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        # Если есть prep_time и cook_time, можем сложить
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            prep_min = int(re.search(r'(\d+)', prep).group(1))
            cook_min = int(re.search(r'(\d+)', cook).group(1))
            total = prep_min + cook_min
            return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с советами в h2 или h3
        all_headers = self.soup.find_all(['h2', 'h3'])
        
        for header in all_headers:
            header_text = header.get_text(strip=True)
            if re.search(r'Consigli|Suggerimenti|Note|Varianti', header_text, re.I):
                # Берем параграф после заголовка
                next_p = header.find_next('p')
                if next_p:
                    notes_text = next_p.get_text(separator=' ', strip=True)
                    notes_text = self.clean_text_italian(notes_text)
                    # Берем первые несколько предложений
                    sentences = re.split(r'[.!?]\s+', notes_text)
                    if len(sentences) > 2:
                        notes_text = '. '.join(sentences[:2]) + '.'
                    return notes_text if notes_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем ключевые слова в заголовке и описании
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем ключевые слова
            words = dish_name.split()
            for word in words:
                if len(word) > 3:
                    tags.append(word)
        
        # Ищем категорию
        category = self.extract_category()
        if category:
            tags.append(category)
        
        # Ищем в meta keywords если есть
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content'].split(',')
            for kw in keywords:
                kw = kw.strip()
                if kw and len(kw) > 2:
                    tags.append(kw)
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем изображения в контенте
        # Ищем img теги в основном контенте
        content_imgs = self.soup.find_all('img')
        for img in content_imgs[:3]:  # Берем первые 3
            src = img.get('src')
            if src and src.startswith('http'):
                urls.append(src)
        
        # Убираем дубликаты
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
                if len(unique_urls) >= 3:
                    break
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Обработка директории с HTML файлами ristoranteilgranduca_it"""
    import os
    
    # Обрабатываем папку preprocessed/ristoranteilgranduca_it
    recipes_dir = os.path.join("preprocessed", "ristoranteilgranduca_it")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RistoranteilgranducaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ristoranteilgranduca_it.py")


if __name__ == "__main__":
    main()
