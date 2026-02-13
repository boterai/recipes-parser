"""
Экстрактор данных рецептов для сайта koktajl.tv
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KoktajlTvExtractor(BaseRecipeExtractor):
    """Экстрактор для koktajl.tv"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Удаляем дополнительное описание после дефиса
            # "WHITE RUSSIAN - deserowy koktajl..." -> "WHITE RUSSIAN"
            if ' - ' in title:
                title = title.split(' - ')[0].strip()
            
            # Удаляем "Przepis na" в начале
            if title.lower().startswith('przepis na'):
                title = title[len('przepis na'):].strip()
            
            # Убираем точку в конце если есть
            title = title.rstrip('.')
            
            # Переводим в Title Case если весь текст в верхнем регистре
            if title.isupper():
                title = title.title()
            # Переводим первую букву в заглавную если текст весь в нижнем регистре
            elif title and title[0].islower():
                title = title[0].upper() + title[1:]
            
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем мета-тег description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Если это подробное описание, берем только первые предложения
            sentences = desc.split('.')
            # Берем до 2 предложений
            result = '.'.join(sentences[:2]).strip()
            if result and not result.endswith('.'):
                result += '.'
            return result
        
        # Пробуем blog-sub-content для страниц с таблицей
        blog_content = self.soup.find('div', class_='blog-sub-content')
        if blog_content:
            p = blog_content.find('p')
            if p:
                text = self.clean_text(p.get_text())
                sentences = text.split('.')
                result = sentences[0].strip() + '.' if sentences else None
                return result
        
        # Ищем в div с классом content
        content_div = self.soup.find('div', class_='content')
        if content_div:
            paragraphs = content_div.find_all('p')
            if paragraphs:
                # Берем текст из первого абзаца
                text = paragraphs[0].get_text().strip()
                # Извлекаем первое предложение
                sentences = text.split('.')
                if sentences and len(sentences[0]) > 0:
                    return self.clean_text(sentences[0] + '.')
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Способ 1: Ищем секцию со Składniki (H3 + div structure)
        ingredients_section = self.soup.find('h3', string=re.compile(r'Składniki', re.I))
        if ingredients_section:
            parent = ingredients_section.parent
            # Находим все строки с ингредиентами
            # BeautifulSoup class matching: use lambda to check for multiple classes
            ingredient_divs = parent.find_all('div', class_=lambda x: x and 'd-flex' in x and 'justify-content-between' in x)
            
            for div in ingredient_divs:
                spans = div.find_all('span')
                if len(spans) == 2:
                    name = self.clean_text(spans[0].get_text())
                    amount_unit_text = self.clean_text(spans[1].get_text())
                    
                    # Парсим amount и unit из текста вида "20.00 ml"
                    amount = None
                    unit = None
                    
                    # Пробуем извлечь число и единицу измерения
                    match = re.match(r'([\d.,]+)\s*(.+)?', amount_unit_text)
                    if match:
                        amount_str = match.group(1).replace(',', '.')
                        try:
                            # Пробуем преобразовать в число
                            amount = float(amount_str)
                            # Если это целое число, конвертируем в int
                            if amount == int(amount):
                                amount = int(amount)
                        except ValueError:
                            amount = amount_str
                        
                        if match.group(2):
                            unit = match.group(2).strip()
                    else:
                        # Если не удалось распарсить, сохраняем как есть
                        amount = amount_unit_text
                    
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
        
        # Способ 2: Ищем таблицу с ингредиентами
        if not ingredients:
            table = self.soup.find('table')
            if table:
                # Ищем заголовок "Składniki"
                th = table.find('th', string=re.compile(r'Składniki', re.I))
                if th:
                    # Находим соответствующую ячейку с данными
                    tr = th.find_parent('tr')
                    if tr:
                        next_tr = tr.find_next_sibling('tr')
                        if next_tr:
                            tds = next_tr.find_all('td')
                            if tds:
                                # Первая ячейка содержит ингредиенты
                                ingredients_text = tds[0].get_text().strip()
                                # Разбиваем по строкам
                                lines = [line.strip() for line in ingredients_text.split('\n') if line.strip()]
                                
                                for line in lines:
                                    # Парсим строки вида "40 ml wódki" или "łyżeczka kakao"
                                    amount = None
                                    unit = None
                                    name = line
                                    
                                    # Пробуем извлечь количество и единицу в начале
                                    # Паттерны: "40 ml wódki", "łyżeczka kakao", "250 gram gorzkiej czekolady"
                                    match = re.match(r'^([\d.,]+)\s+(\w+)\s+(.+)$', line)
                                    if match:
                                        amount_str = match.group(1).replace(',', '.')
                                        try:
                                            amount = float(amount_str)
                                            if amount == int(amount):
                                                amount = int(amount)
                                        except ValueError:
                                            amount = amount_str
                                        unit = match.group(2)
                                        name = match.group(3)
                                    else:
                                        # Пробуем паттерн "łyżeczka kakao" (единица в начале)
                                        match = re.match(r'^(\d+\s+)?(\w+)\s+(.+)$', line)
                                        if match:
                                            if match.group(1):  # Есть количество
                                                try:
                                                    amount = int(match.group(1).strip())
                                                except ValueError:
                                                    pass
                                            unit = match.group(2)
                                            name = match.group(3)
                                    
                                    ingredients.append({
                                        "name": self.clean_text(name),
                                        "units": unit,
                                        "amount": amount
                                    })
        
        if ingredients:
            # Возвращаем как JSON строку, как в примерах
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Способ 1: Ищем заголовок "Sposób przygotowania" (Способ приготовления)
        instructions_header = self.soup.find('h2', string=re.compile(r'Sposób przygotowania', re.I))
        if instructions_header:
            # Следующий row должен содержать инструкции
            next_row = instructions_header.find_parent('div', class_='row')
            if next_row:
                next_sibling = next_row.find_next_sibling('div', class_='row')
                if next_sibling:
                    p = next_sibling.find('p')
                    if p:
                        return self.clean_text(p.get_text())
        
        # Способ 2: Ищем в таблице
        table = self.soup.find('table')
        if table:
            # Ищем заголовок "Sposób przygotowania"
            th = table.find('th', string=re.compile(r'Sposób przygotowania', re.I))
            if th:
                # Находим соответствующую ячейку с данными
                tr = th.find_parent('tr')
                if tr:
                    next_tr = tr.find_next_sibling('tr')
                    if next_tr:
                        tds = next_tr.find_all('td')
                        if len(tds) > 1:
                            # Вторая ячейка содержит инструкции
                            instructions_text = tds[1].get_text().strip()
                            # Заменяем <br> на пробелы
                            instructions_text = re.sub(r'\s+', ' ', instructions_text)
                            return self.clean_text(instructions_text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем различные места, где может быть категория
        # В примерах видим "Drink" и "Dessert"
        
        # Проверяем breadcrumbs или navigation
        breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb|path', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Последняя ссылка обычно категория
            if links and len(links) > 1:
                category = self.clean_text(links[-1].get_text())
                if category and category.lower() not in ['home', 'главная', 'drinki']:
                    return category
        
        # Проверяем data-type атрибут
        drink_container = self.soup.find('div', id='drink')
        if drink_container and drink_container.get('data-type'):
            return drink_container['data-type']
        
        # Определяем категорию на основе контента
        # Если в описании или названии упоминается десерт - это Dessert
        description = self.extract_description()
        dish_name = self.extract_dish_name()
        combined_text = f"{dish_name or ''} {description or ''}".lower()
        
        if combined_text:
            # Ключевые слова для категории Dessert
            if re.search(r'deser|czekolad|słod|ciast', combined_text, re.I):
                return "Dessert"
        
        # Проверяем теги
        tags = self.extract_tags()
        if tags:
            tags_lower = tags.lower()
            if 'deserowe' in tags_lower or 'słodkie' in tags_lower:
                return "Dessert"
            # Если упоминается только напитки, то Drink
            if 'drinki' in tags_lower and 'deserowe' not in tags_lower:
                return "Drink"
        
        # По умолчанию возвращаем None, так как не всегда можно определить категорию
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В примерах это поле всегда None
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # В примерах это поле всегда None
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В примерах это поле всегда None
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # Ищем в content div или blog-sub-content параграфы с советами/рекомендациями
        content_divs = [
            self.soup.find('div', class_='content'),
            self.soup.find('div', class_='blog-sub-content')
        ]
        
        for content_div in content_divs:
            if not content_div:
                continue
            
            paragraphs = content_div.find_all('p')
            # Ищем параграфы с ключевыми словами советов
            for p in paragraphs:
                text = p.get_text()
                # Если находим параграф с советами (ключевые слова)
                if re.search(r'wybierz|sprawdź|uwag|wskazówk|użyj|raczej', text, re.I):
                    # Извлекаем чистый текст
                    clean = self.clean_text(text)
                    # Берем предложения, содержащие совет
                    sentences = clean.split('.')
                    useful_sentences = []
                    for sentence in sentences:
                        sentence = sentence.strip()
                        # Ищем предложения с советами/рекомендациями
                        if re.search(r'wybierz|sprawdź|użyj|raczej|można|sprawdźcie', sentence, re.I):
                            useful_sentences.append(sentence)
                        # Ограничиваем количество предложений
                        if len(useful_sentences) >= 2:
                            break
                    
                    if useful_sentences:
                        result = '. '.join(useful_sentences)
                        if not result.endswith('.'):
                            result += '.'
                        return result
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем секцию с тегами
        tags_section = self.soup.find('span', string=re.compile(r'Tagi:', re.I))
        if tags_section:
            parent = tags_section.find_parent('div', class_='blog-sub-tags')
            if parent:
                tag_links = parent.find_all('a')
                tags = [self.clean_text(a.get_text()) for a in tag_links]
                if tags:
                    # Возвращаем теги через запятую с пробелом
                    return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Основное изображение блюда
        drink_picture = self.soup.find('div', class_='drink-picture')
        if drink_picture:
            img = drink_picture.find('img')
            if img and img.get('src'):
                image_urls.append(img['src'])
        
        # Дополнительные изображения из галереи компонентов
        gallery_items = self.soup.find_all('div', class_='gallery-item')
        for item in gallery_items:
            # Проверяем background-image в style
            style = item.get('style', '')
            match = re.search(r"url\(['\"]?([^'\"]+)['\"]?\)", style)
            if match:
                url = match.group(1)
                if url and url not in image_urls:
                    image_urls.append(url)
            
            # Также проверяем ссылки внутри
            link = item.find('a')
            if link and link.get('href'):
                href = link['href']
                if href and href not in image_urls:
                    # Добавляем только если это похоже на изображение
                    if re.search(r'\.(jpg|jpeg|png|gif|webp)', href, re.I):
                        image_urls.append(href)
        
        if image_urls:
            # Возвращаем через запятую без пробелов
            return ','.join(image_urls)
        
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта из HTML"""
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
    """Точка входа для обработки HTML файлов koktajl.tv"""
    # Путь к директории с preprocessed файлами
    preprocessed_dir = Path(__file__).parent.parent / 'preprocessed' / 'koktajl_tv'
    
    if not preprocessed_dir.exists():
        print(f"Директория {preprocessed_dir} не найдена!")
        return
    
    print(f"Обработка файлов из {preprocessed_dir}")
    process_directory(KoktajlTvExtractor, str(preprocessed_dir))


if __name__ == '__main__':
    main()
