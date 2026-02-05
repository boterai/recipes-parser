"""
Экстрактор данных рецептов для сайта sweetandbitter.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SweetAndBitterExtractor(BaseRecipeExtractor):
    """Экстрактор для sweetandbitter.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
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
            ingredient_text: Строка вида "500γρ. αλεύρι" или "6 αβγά"
            
        Returns:
            dict: {"name": "αλεύρι", "amount": "500", "units": "γρ."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500γρ. αλεύρι", "6 αβγά", "2 κ.γλυκού baking powder"
        # Единицы: γρ. (грамм), κ. (ложка), φλ. (чашка), λ. (литр), ΤΒ (столовая ложка), κ.γλυκού (чайная ложка)
        
        # Сначала попробуем паттерн с единицей измерения (слитно с числом)
        # Формат: "500γρ. название"
        pattern = r'^(\d+(?:[.,]\d+)?)(γρ\.|κ\.|φλ\.|λ\.|ΤΒ|κ\.γλυκού|κ\.σούπας)\s+(.+)$'
        match = re.match(pattern, text)
        
        if match:
            amount, unit, name = match.groups()
            # Очистка названия от HTML тегов
            name = re.sub(r'<[^>]+>', '', name)
            return {
                "name": name.strip(),
                "amount": int(amount) if amount.isdigit() else amount,
                "units": unit.strip()
            }
        
        # Паттерн с единицей, разделенной пробелом
        # Формат: "2 κ.γλυκού baking powder"
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(γρ\.|κ\.|φλ\.|λ\.|ΤΒ|κ\.γλυκού|κ\.σούπας)\s+(.+)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            amount, unit, name = match2.groups()
            name = re.sub(r'<[^>]+>', '', name)
            return {
                "name": name.strip(),
                "amount": int(amount) if amount.isdigit() else amount,
                "units": unit.strip()
            }
        
        # Паттерн без единицы измерения (только число + название)
        # Формат: "6 αβγά"
        pattern3 = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match3 = re.match(pattern3, text)
        
        if match3:
            amount, name = match3.groups()
            name = re.sub(r'<[^>]+>', '', name)
            return {
                "name": name.strip(),
                "amount": int(amount) if amount.isdigit() else amount,
                "units": None
            }
        
        # Паттерн для специальных случаев типа "μια πρέζα αλάτι" (щепотка соли)
        if 'πρέζα' in text or 'λίγο' in text:
            return {
                "name": text,
                "amount": text,  # Вся строка как количество для таких случаев
                "units": None
            }
        
        # Если ничего не совпало, возвращаем как название без количества
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов
        # На sweetandbitter.gr ингредиенты находятся в UL без класса или с пустым классом
        # Может быть несколько таких UL (для разных частей рецепта, например тесто и крем)
        all_uls = self.soup.find_all('ul')
        
        for ul in all_uls:
            # Сначала проверяем, есть ли UL без класса с прямыми LI-ингредиентами
            classes = ul.get('class', [])
            
            # Если UL не имеет классов или имеет пустой класс
            if not classes or classes == []:
                lis = ul.find_all('li', recursive=False)  # Только прямые дети
                
                # Проверяем, что это список ингредиентов
                if lis and len(lis) >= 3:  # Минимум 3 ингредиента
                    first_li_text = lis[0].get_text().strip()
                    # Проверяем, что первый элемент похож на ингредиент 
                    # (содержит число в начале или греческие буквы характерные для ингредиентов)
                    if (re.match(r'^\d+', first_li_text) or 
                        any(word in first_li_text.lower() for word in ['αβγά', 'ζάχαρη', 'αλεύρι', 'βούτυρο', 'βανίλ', 'πρέζα'])):
                        
                        for li in lis:
                            text = li.get_text(separator=' ', strip=True)
                            
                            # Пропускаем пустые элементы
                            if not text:
                                continue
                            
                            # Парсим ингредиент
                            parsed = self.parse_ingredient(text)
                            if parsed and parsed.get('name'):
                                ingredients.append(parsed)
                        
                        # Не прекращаем поиск - может быть еще UL с ингредиентами
                        # (например, для теста и крема в тортах)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем контейнер с инструкциями
        inst_container = self.soup.find('div', class_=re.compile(r'recipe_instructionsContainer'))
        
        if inst_container:
            # Извлекаем весь текст из контейнера
            text = inst_container.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # В примерах видим "Dessert" - это может быть из мета-тегов или хлебных крошек
        # Проверяем мета-теги
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Проверяем хлебные крошки (breadcrumbs)
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if links:
                # Берем последнюю категорию перед рецептом
                categories = []
                for link in links:
                    text = self.clean_text(link.get_text())
                    href = link.get('href', '')
                    # Пропускаем главную страницу
                    if text and text.lower() not in ['home', 'главная', 'αρχική']:
                        categories.append(text)
                
                if categories:
                    return categories[-1]
        
        # Для сайта sweetandbitter.gr можно также проверить ссылки на категории
        for link in self.soup.find_all('a'):
            href = link.get('href', '')
            if '/category/' in href.lower() or '/categories/' in href.lower():
                text = self.clean_text(link.get_text())
                if text and len(text) < 50:  # Разумная длина для категории
                    return text
        
        return None
    
    def extract_time_value(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Греческие термины для времени
        time_patterns = {
            'prep': r'Χρόνος\s+προετοιμασίας:\s*(\d+)\s*λεπτ',
            'cook': r'Χρόνος\s+ψησίματος:\s*(\d+)\s*λεπτ',
            'total': r'Συνολικός\s+χρόνος:\s*(\d+)\s*λεπτ'
        }
        
        pattern = time_patterns.get(time_type)
        if not pattern:
            return None
        
        # Ищем в тексте всей страницы
        page_text = self.soup.get_text()
        
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            minutes = match.group(1)
            return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_value('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_value('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Для sweetandbitter.gr общее время обычно вычисляется
        total = self.extract_time_value('total')
        
        if total:
            return total
        
        # Если нет явного total_time, можем попробовать сложить prep и cook
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_num = re.search(r'(\d+)', prep)
            cook_num = re.search(r'(\d+)', cook)
            
            if prep_num and cook_num:
                total_minutes = int(prep_num.group(1)) + int(cook_num.group(1))
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с примечаниями
        # В греческом могут быть слова: "Προσοχή", "Σημείωση", "Συμβουλή"
        
        # Сначала попробуем найти отдельные блоки с классами note/tip
        for tag in self.soup.find_all(['div', 'p'], class_=True):
            classes = ' '.join(tag.get('class', []))
            
            # Проверяем классы (избегаем instructionsContainer)
            if (any(keyword in classes.lower() for keyword in ['note', 'tip', 'warning']) and
                'instruction' not in classes.lower()):
                text = tag.get_text(strip=True)
                return self.clean_text(text)
        
        # Если отдельных блоков нет, ищем в инструкциях предложения с "Προσοχή"
        instructions = self.extract_instructions()
        if instructions:
            # Ищем "Προσοχή!" и берем следующее предложение
            # Паттерн: "Προσοχή! Текст заметки."
            match = re.search(r'Προσοχή!\s*([^.!]+[.!])', instructions)
            if match:
                note = match.group(1).strip()
                # Убираем завершающую точку/восклицательный знак для чистоты
                note = re.sub(r'[.!]+$', '', note)
                return self.clean_text(note) if note else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в мета-тегах
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Также можем искать теги в мета og:article:tag
        og_tags = self.soup.find_all('meta', property='article:tag')
        for tag in og_tags:
            if tag.get('content'):
                tags_list.append(tag['content'].strip())
        
        # Ищем UL с тегами (имеет специфические классы)
        # Обычно это UL с классами font-bold и flex
        if not tags_list:
            for ul in self.soup.find_all('ul', class_=True):
                classes = ' '.join(ul.get('class', []))
                if 'font-bold' in classes and 'flex' in classes:
                    # Это скорее всего UL с тегами
                    lis = ul.find_all('li')
                    for li in lis:
                        # Проверяем, что это ссылка на тег
                        link = li.find('a', href=True)
                        if link and '/tag/' in link.get('href', ''):
                            tag_text = link.get_text().strip()
                            if tag_text:
                                tags_list.append(tag_text)
        
        # Возвращаем теги через запятую с пробелом
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем изображения в теле страницы
        # Для Next.js сайтов часто используются img с src или data-src
        img_tags = self.soup.find_all('img')
        for img in img_tags:
            src = img.get('src', '') or img.get('data-src', '')
            
            # Фильтруем только изображения рецептов (содержат cms.sweetandbitter.gr или полные URL)
            if src and ('cms.sweetandbitter.gr' in src or src.startswith('http')):
                # Извлекаем оригинальный URL из Next.js image URL
                # Формат: /_next/image?url=https%3A%2F%2Fcms.sweetandbitter.gr%2F...
                if '/_next/image?url=' in src:
                    match = re.search(r'url=([^&]+)', src)
                    if match:
                        import urllib.parse
                        decoded_url = urllib.parse.unquote(match.group(1))
                        urls.append(decoded_url)
                elif src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            # Берем только URL без query параметров для сравнения
            url_base = url.split('&w=')[0].split('?w=')[0]
            if url_base not in seen:
                seen.add(url_base)
                unique_urls.append(url_base)
        
        # Возвращаем как строку через запятую (без пробелов)
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка HTML файлов из preprocessed/sweetandbitter_gr"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "sweetandbitter_gr")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SweetAndBitterExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python sweetandbitter_gr.py")


if __name__ == "__main__":
    main()
