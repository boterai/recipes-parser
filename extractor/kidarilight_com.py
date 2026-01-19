"""
Экстрактор данных рецептов для сайта kidarilight.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KidarilightExtractor(BaseRecipeExtractor):
    """Экстрактор для kidarilight.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Очищаем название от префиксов типа "엄마의 비건 레시피 _"
            # Убираем всё до символа "_"
            if '_' in title:
                # Берем всё после "_"
                title = title.split('_', 1)[-1].strip()
            # Убираем суффиксы типа "과 ..." (и ...)
            if '과 ' in title:
                title = title.split('과 ')[0].strip()
            return self.clean_text(title)
        
        # Альтернативно - из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из текста рецепта"""
        ingredients = []
        found_ingredients = set()
        
        # Ищем основной контент статьи
        content = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content:
            return None
        
        # Получаем весь текст контента
        full_text = content.get_text()
        
        # Список всех возможных ингредиентов, которые мы ищем
        # Будем искать их упоминания в тексте
        common_ingredients = [
            '대파', '편마늘', '마늘', '양파', '감자', '당근', '파프리카', '애호박', 
            '브로콜리', '토마토', '버섯', '양배추', '얼린두부', '두부', '물', 
            '카레가루', '강황분말', '가람마살라', '전분가루', '쌀가루', '간장', 
            '소금', '기름', '참기름', '깨', '고춧가루', '후추', '설탕', '식초',
            '도라지', '미역줄기', '고춧잎', '청경채', '올리고당', '콩', '고기',
            '해산물', '돼지고기', '닭고기', '소고기', '새우', '오징어', '조개',
            '양송이버섯', '팽이버섯', '느타리버섯', '표고버섯'
        ]
        
        # Ищем ингредиенты в тексте
        for ing in common_ingredients:
            if ing in full_text:
                # Проверяем, не добавили ли уже этот ингредиент
                if ing not in found_ingredients:
                    # Пробуем найти количество рядом с ингредиентом
                    # Паттерн: "토마토 2개" или просто "토마토"
                    pattern = rf'{ing}\s*(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z]+)?'
                    match = re.search(pattern, full_text)
                    
                    if match and match.group(1):
                        # Нашли количество и возможно единицу
                        amount = match.group(1)
                        units = match.group(2) if match.group(2) else None
                        ingredients.append({
                            "name": ing,
                            "amount": amount,
                            "units": units
                        })
                    else:
                        # Только название без количества
                        ingredients.append({
                            "name": ing,
                            "amount": None,
                            "units": None
                        })
                    
                    found_ingredients.add(ing)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_korean(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг корейского ингредиента
        
        Args:
            ingredient_text: Строка вида "토마토 2개" или "물"
            
        Returns:
            dict: {"name": "토마토", "amount": "2", "units": "개"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества и единицы измерения
        # Примеры: "토마토 2개", "물 500ml", "소금 1스푼"
        pattern = r'^(.+?)\s*(\d+(?:\.\d+)?)\s*([가-힣a-zA-Z]+)$'
        match = re.match(pattern, text)
        
        if match:
            name, amount, units = match.groups()
            return {
                "name": name.strip(),
                "amount": amount,
                "units": units
            }
        
        # Если нет количества, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем основной контент
        content = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content:
            return None
        
        # Ищем параграфы с инструкциями
        paragraphs = content.find_all('p')
        
        for p in paragraphs:
            text = p.get_text()
            
            # Ищем строки, начинающиеся с цифр (шаги рецепта)
            # Паттерн: "1. текст" или "**1.**текст" или просто текст с цифрами
            lines = text.split('\n')
            for line in lines:
                line = self.clean_text(line)
                
                # Проверяем, начинается ли с цифры и точки
                if re.match(r'^\*?\*?\d+\.', line):
                    # Убираем звездочки и пробелы в начале
                    line = re.sub(r'^\*+', '', line).strip()
                    instructions.append(line)
        
        # Если не нашли пронумерованные шаги, ищем просто текст с инструкциями
        if not instructions:
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Ищем параграфы с глаголами действия (корейские глаголы часто заканчиваются на -다, -요, -니다)
                if text and len(text) > 20 and any(word in text for word in ['넣', '끓', '구', '썰', '볶']):
                    # Разбиваем по предложениям
                    sentences = re.split(r'\.\s+', text)
                    for i, sent in enumerate(sentences, 1):
                        sent = sent.strip()
                        if sent and len(sent) > 10:
                            if not re.match(r'^\d+\.', sent):
                                sent = f"{i}. {sent}"
                            if sent not in instructions:
                                instructions.append(sent)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Маппинг корейских категорий на английские
        category_mapping = {
            '너무쉬운, 엄마의 레시피': 'Main Course',
            '엄마의 레시피': 'Main Course',
            '레시피': 'Main Course',
            '반찬': 'Side Dish',
            '밑반찬': 'Side Dish',
            '디저트': 'Dessert',
            '후식': 'Dessert',
            '국': 'Soup',
            '찌개': 'Stew',
        }
        
        # Ищем в span с классом category
        category_span = self.soup.find('span', class_='category')
        if category_span:
            cat_text = category_span.get_text()
            # Убираем номера типа "6. "
            cat_text = re.sub(r'^\d+\.\s*', '', cat_text)
            cat_text = self.clean_text(cat_text)
            
            # Пробуем маппинг
            for korean, english in category_mapping.items():
                if korean in cat_text:
                    return english
            
            return cat_text
        
        # Альтернативно - из categoryLabel в JavaScript
        scripts = self.soup.find_all('script', type='text/javascript')
        for script in scripts:
            if script.string and 'categoryLabel' in script.string:
                match = re.search(r'"categoryLabel"\s*:\s*"([^"]+)"', script.string)
                if match:
                    cat_text = match.group(1)
                    cat_text = re.sub(r'^\d+\.\s*', '', cat_text)
                    cat_text = self.clean_text(cat_text)
                    
                    # Пробуем маппинг
                    for korean, english in category_mapping.items():
                        if korean in cat_text:
                            return english
                    
                    return cat_text
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Для этого сайта время обычно не указывается явно
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Для этого сайта время обычно не указывается явно
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Для этого сайта время обычно не указывается явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем основной контент
        content = self.soup.find('div', class_='tt_article_useless_p_margin')
        if not content:
            return None
        
        paragraphs = content.find_all('p')
        
        for p in paragraphs:
            text = self.clean_text(p.get_text())
            
            # Ищем параграфы, начинающиеся с ** (маркер заметок)
            if text.startswith('**') or '**' in text[:20]:
                # Убираем звездочки
                note = re.sub(r'\*+', '', text).strip()
                if note and len(note) > 5:
                    notes.append(note)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем div с классом tags
        tags_div = self.soup.find('div', class_='tags')
        if not tags_div:
            return None
        
        # Извлекаем все ссылки с rel="tag"
        tag_links = tags_div.find_all('a', rel='tag')
        if not tag_links:
            return None
        
        tags = [self.clean_text(tag.get_text()) for tag in tag_links]
        
        # Возвращаем как строку через запятую
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', property='twitter:image')
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем изображения в контенте статьи
        content = self.soup.find('div', class_='tt_article_useless_p_margin')
        if content:
            # Ищем все figure с изображениями
            figures = content.find_all('figure', class_='imageblock')
            for fig in figures[:5]:  # Ограничиваем до 5 изображений
                img = fig.find('img')
                if img and img.get('src'):
                    url = img['src']
                    if url not in urls:
                        urls.append(url)
        
        # Убираем дубликаты и возвращаем как строку через запятую
        if urls:
            return ','.join(urls)
        
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
    import os
    # Обрабатываем папку preprocessed/kidarilight_com
    recipes_dir = os.path.join("preprocessed", "kidarilight_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KidarilightExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kidarilight_com.py")


if __name__ == "__main__":
    main()
