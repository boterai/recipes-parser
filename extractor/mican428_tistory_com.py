"""
Экстрактор данных рецептов для сайта mican428.tistory.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Mican428TistoryComExtractor(BaseRecipeExtractor):
    """Экстрактор для mican428.tistory.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в div.post-cover h1 (это заголовок поста, а не блога)
        post_cover = self.soup.find('div', class_='post-cover')
        if post_cover:
            h1 = post_cover.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Также можно извлечь из JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'headline' in data:
                    return self.clean_text(data['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем только первое предложение из описания (до первой точки или до 200 символов)
            # так как в meta description может быть длинный текст
            sentences = desc.split('. ')
            if sentences:
                first_sentence = sentences[0].strip()
                if first_sentence:
                    return self.clean_text(first_sentence + '.')
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            sentences = desc.split('. ')
            if sentences:
                first_sentence = sentences[0].strip()
                if first_sentence:
                    return self.clean_text(first_sentence + '.')
        
        return None
    
    def parse_ingredient_text(self, text: str) -> list:
        """
        Парсинг строки с ингредиентами в структурированный формат
        
        Args:
            text: Строка вида "말린 시래기 100g, 된장 2큰술, 고추장 1큰술"
            
        Returns:
            list: [{"name": "말린 시래기", "amount": 100, "units": "g"}, ...]
        """
        ingredients = []
        
        # Разделяем по запятым
        parts = text.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Паттерны для извлечения: название количество единица
            # Пример: "말린 시래기 100g" или "된장 2큰술" или "소금 약간"
            
            # Вариант 1: название количество+единица слитно (100g, 2큰술)
            match = re.match(r'^(.+?)\s+(\d+(?:\.\d+)?)(g|ml|컵|큰술|스푼|개|약간|적당량)(.*)$', part)
            if match:
                name = match.group(1).strip()
                amount = match.group(2)
                units = match.group(3)
                extra = match.group(4).strip()
                
                # Если есть дополнительная информация в скобках, добавляем к units
                if extra and extra.startswith('('):
                    units = units + ' ' + extra
                
                # Преобразуем amount в число если возможно
                try:
                    amount = int(amount) if '.' not in amount else float(amount)
                except ValueError:
                    pass
                
                ingredients.append({
                    "name": name,
                    "units": units,
                    "amount": amount
                })
                continue
            
            # Вариант 2: название количество единица раздельно (100 g, 2 큰술)
            match = re.match(r'^(.+?)\s+(\d+(?:\.\d+)?)\s*(g|ml|컵|큰술|스푼|개|약간|적당량)(.*)$', part)
            if match:
                name = match.group(1).strip()
                amount = match.group(2)
                units = match.group(3)
                extra = match.group(4).strip()
                
                if extra and extra.startswith('('):
                    units = units + ' ' + extra
                
                try:
                    amount = int(amount) if '.' not in amount else float(amount)
                except ValueError:
                    pass
                
                ingredients.append({
                    "name": name,
                    "units": units,
                    "amount": amount
                })
                continue
            
            # Вариант 3: только название и единица без количества (약간, 적당량)
            match = re.match(r'^(.+?)\s+(약간|적당량)$', part)
            if match:
                name = match.group(1).strip()
                units = match.group(2)
                
                ingredients.append({
                    "name": name,
                    "units": units,
                    "amount": None
                })
                continue
            
            # Если ничего не подошло, добавляем как есть
            ingredients.append({
                "name": part,
                "units": None,
                "amount": None
            })
        
        return ingredients
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем текст с ингредиентами
        content_div = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content_div:
            content_div = self.soup.find('div', class_='contents_style')
        
        if content_div:
            # Ищем параграфы с data-ke-size
            paragraphs = content_div.find_all('p', attrs={'data-ke-size': True})
            
            for p in paragraphs:
                text = p.get_text(strip=True)
                
                # Вариант 1: Проверяем, содержит ли параграф слово "재료" и "준비"
                if '재료' in text and '준비' in text:
                    # Извлекаем только часть после "재료 준비"
                    parts = text.split('재료 준비')
                    if len(parts) > 1:
                        ingredient_text = parts[1].strip()
                        # Убираем начальные символы типа ":", "-", "하기"
                        ingredient_text = re.sub(r'^[:\-\s하기필요한다음과같습니다]+', '', ingredient_text)
                        ingredients = self.parse_ingredient_text(ingredient_text)
                        if ingredients:
                            break
                
                # Вариант 2: Если текст начинается с ингредиентов (например, "건미역 30g, 소고기 100g...")
                # и содержит характерные единицы измерения
                if not ingredients and re.search(r'\d+(g|ml|컵|큰술|스푼|개)', text):
                    # Проверяем, что это не часть инструкции (нет глаголов действия)
                    if not any(word in text for word in ['넣고', '볶습니다', '끓입니다', '준비합니다', '자릅니다']):
                        # Это может быть список ингредиентов
                        ingredients = self.parse_ingredient_text(text)
                        if len(ingredients) >= 3:  # Минимум 3 ингредиента
                            break
        
        # Паттерн 3: ищем в таблицах
        if not ingredients:
            tables = self.soup.find_all('table')
            for table in tables:
                cells = table.find_all('td')
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if '재료' in text:
                        # Извлекаем текст после "재료 -"
                        parts = text.split('재료')
                        if len(parts) > 1:
                            ingredient_text = parts[1].strip()
                            ingredient_text = re.sub(r'^[:\-\s]+', '', ingredient_text)
                            ingredients = self.parse_ingredient_text(ingredient_text)
                            if ingredients:
                                break
                if ingredients:
                    break
        
        # Возвращаем как JSON строку
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions_parts = []
        
        # Ищем параграфы после раздела с ингредиентами
        content_div = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content_div:
            content_div = self.soup.find('div', class_='contents_style')
        
        if content_div:
            paragraphs = content_div.find_all('p', attrs={'data-ke-size': True})
            
            found_ingredients = False
            step_counter = 1
            
            for p in paragraphs:
                text = p.get_text(separator=' ', strip=True)
                
                # Пропускаем до раздела с ингредиентами
                if '재료' in text or 'ingredient' in text.lower():
                    found_ingredients = True
                    continue
                
                # После раздела с ингредиентами ищем инструкции
                if found_ingredients and text:
                    # Пропускаем заголовки секций
                    if text in ['만드는 방법', '조리법', '만드는법']:
                        continue
                    
                    # Разбиваем параграф на секции (по заголовкам вида "준비하기", "볶기", etc.)
                    # Ищем паттерны: текст + "하기" или "볶기" или "끓이기" и т.д.
                    sections = re.split(r'(\S+\s*(?:준비하기|볶기|끓이기|만들기|조리하기))', text)
                    
                    for i, section in enumerate(sections):
                        section = section.strip()
                        if not section:
                            continue
                        
                        # Пропускаем сами заголовки секций
                        if re.match(r'\S+\s*(?:준비하기|볶기|끓이기|만들기|조리하기)$', section):
                            continue
                        
                        # Если секция содержит действия (глаголы)
                        if any(verb in section for verb in ['합니다', '넣고', '볶아', '끓', '담가', '자릅니다', '제거', '부어', '섞', '추가']):
                            # Разбиваем на предложения
                            sentences = re.split(r'(?<=[다요])\.\s*|\s+(?=\d+\.)', section)
                            for sent in sentences:
                                sent = sent.strip('. ')
                                if sent and len(sent) > 10:  # Минимальная длина предложения
                                    # Если предложение уже нумеровано, используем его
                                    if re.match(r'^\d+\.', sent):
                                        instructions_parts.append(sent)
                                    else:
                                        # Добавляем нумерацию
                                        instructions_parts.append(f"{step_counter}. {sent}")
                                        step_counter += 1
        
        # Объединяем все инструкции
        if instructions_parts:
            return ' '.join(instructions_parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в span.category
        category_span = self.soup.find('span', class_='category')
        if category_span:
            category_text = self.clean_text(category_span.get_text())
            # Переводим на английский для консистентности
            # "요리" -> "Main Course", "간식" -> "간식"
            if category_text == '요리':
                return 'Main Course'
            elif category_text == '간식':
                return '간식'
            return category_text
        
        # Альтернативно из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category_text = self.clean_text(meta_section['content']).strip("'")
            if category_text == '요리':
                return 'Main Course'
            elif category_text == '간식':
                return '간식'
            return category_text
        
        return None
    
    def extract_time_info(self) -> tuple:
        """
        Извлечение информации о времени (prep_time, cook_time, total_time)
        
        Returns:
            tuple: (prep_time, cook_time, total_time)
        """
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем в тексте статьи упоминания времени
        content_div = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content_div:
            content_div = self.soup.find('div', class_='contents_style')
        
        if content_div:
            text = content_div.get_text()
            
            # Ищем prep_time (время подготовки)
            prep_match = re.search(r'준비\s*시간[:\s]*(\d+)\s*(분|minutes?)', text, re.IGNORECASE)
            if prep_match:
                prep_time = f"{prep_match.group(1)} minutes"
            
            # Ищем cook_time (время готовки)
            cook_match = re.search(r'조리\s*시간[:\s]*(\d+)\s*(분|minutes?)', text, re.IGNORECASE)
            if cook_match:
                cook_time = f"{cook_match.group(1)} minutes"
            
            # Ищем total_time (общее время)
            total_match = re.search(r'총\s*시간[:\s]*(\d+)\s*(분|minutes?)', text, re.IGNORECASE)
            if total_match:
                total_time = f"{total_match.group(1)} minutes"
        
        return prep_time, cook_time, total_time
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями или советами
        content_div = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content_div:
            content_div = self.soup.find('div', class_='contents_style')
        
        if content_div:
            paragraphs = content_div.find_all('p', attrs={'data-ke-size': True})
            
            # Ищем последние 2-3 параграфа, которые могут быть примечаниями
            # Обычно примечания идут после инструкций
            last_paragraphs = list(reversed(paragraphs[-3:]))
            
            for p in last_paragraphs:
                text = p.get_text(strip=True)
                
                # Проверяем на ключевые слова для примечаний
                # И что это не слишком длинный параграф (примечания обычно короткие)
                if len(text) < 300 and any(word in text for word in ['팁', '주의', '참고', '추천', '좋으며', '맛있다', '보양식', '건강', '먹으면']):
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в tiara tracking script
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'window.tiara' in script.string:
                # Ищем массив tags в JSON
                match = re.search(r'"tags":\s*\[(.*?)\]', script.string)
                if match:
                    tags_str = match.group(1)
                    # Извлекаем строки из массива
                    tags = re.findall(r'"([^"]+)"', tags_str)
                    break
        
        # Если не нашли в tiara, ищем в meta keywords
        if not tags:
            meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords['content']
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        url = img['url']
                        if url not in urls:
                            urls.append(url)
                    elif isinstance(img, str) and img not in urls:
                        urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем в figure элементах (изображения в статье)
        figures = self.soup.find_all('figure', class_='imageblock')
        for figure in figures:
            # Ищем data-url атрибут
            span = figure.find('span', attrs={'data-url': True})
            if span:
                url = span.get('data-url')
                if url and url not in urls:
                    urls.append(url)
            
            # Или в img src
            img = figure.find('img')
            if img and img.get('src'):
                url = img['src']
                if url and url not in urls:
                    urls.append(url)
        
        # Ограничиваем до разумного количества (например, первые 5)
        urls = urls[:5]
        
        return ','.join(urls) if urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time, cook_time, total_time = self.extract_time_info()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/mican428_tistory_com
    preprocessed_dir = os.path.join("preprocessed", "mican428_tistory_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(Mican428TistoryComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mican428_tistory_com.py")


if __name__ == "__main__":
    main()
