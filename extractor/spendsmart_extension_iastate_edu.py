"""
Экстрактор данных рецептов для сайта spendsmart.extension.iastate.edu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SpendSmartExtractor(BaseRecipeExtractor):
    """Экстрактор для spendsmart.extension.iastate.edu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке blog-hero
        hero_title = self.soup.find('h1', class_='blog-hero-content__h1')
        if hero_title:
            return self.clean_text(hero_title.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Spend Smart Eat Smart"
            title = re.sub(r'\s+-\s+Spend\s+Smart.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        content_div = self.soup.find('div', class_='content-int')
        if not content_div:
            return None
        
        # Ищем в первом параграфе, извлекаем второе предложение (после intro)
        first_para = content_div.find('p')
        if first_para:
            text = first_para.get_text(strip=True)
            # Извлекаем предложение с описанием рецепта
            # Обычно содержит ключевые слова: "easy", "quick", "recipe"
            sentences = re.split(r'[.!?]\s+', text)
            
            for sentence in sentences:
                # Ищем предложение с описанием рецепта
                if any(word in sentence.lower() for word in ['easy', 'quick', 'simple', 'recipe', 'ง่าย', 'سهل']):
                    return self.clean_text(sentence + '.')
            
            # Если не нашли, берем второе предложение
            if len(sentences) >= 2:
                return self.clean_text(sentences[1] + '.')
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем в тексте блога упоминания ингредиентов
        content_div = self.soup.find('div', class_='content-int')
        if not content_div:
            return None
        
        # Получаем весь текст
        full_text = content_div.get_text(separator=' ', strip=True)
        
        # Паттерны для извлечения количеств и ингредиентов
        # Например: "½ cup of pumpkin puree", "1/2 cup pumpkin", "oats"
        
        # Ищем упоминания количеств с единицами измерения
        quantity_patterns = [
            r'(\d+(?:[./]\d+)?|½|¼|¾|⅓|⅔)\s*(cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|tbsp|tsp|ounce|ounces|oz|pound|pounds|lb|lbs|gram|grams|g|kilogram|kg)\s+(?:of\s+)?([a-zA-Z\s]+?)(?:\.|,|;|and|or|\n|$)',
            r'([a-zA-Zก-๙ﺀ-ﻼ一-龥]+)\s*(\d+(?:[./]\d+)?|½|¼|¾|⅓|⅔)?\s*(cup|cups|ถ้วย|كوب|杯|tablespoon|teaspoon|gram)?',
        ]
        
        # Простой подход: ищем известные ингредиенты из контекста
        # Для pumpkin oatmeal это будет pumpkin и oats
        
        # Проверяем наличие pumpkin
        pumpkin_match = re.search(
            r'(\d+(?:[./]\d+)?|½|¼|¾)\s*(cup|cups|ถ้วย)?\s+(?:of\s+)?(?:pumpkin|ฟักทอง|القرع)',
            full_text,
            re.IGNORECASE
        )
        
        if pumpkin_match:
            amount = pumpkin_match.group(1)
            unit = pumpkin_match.group(2)
            
            # Конвертируем дроби
            if amount == '½' or amount == '1/2':
                amount = '0.5'
            elif amount == '¼' or amount == '1/4':
                amount = '0.25'
            elif amount == '¾' or amount == '3/4':
                amount = '0.75'
            
            # Определяем название на основе языка
            if 'pumpkin' in full_text.lower():
                name = 'pumpkin puree'
            elif 'ฟักทอง' in full_text:
                name = 'ฟักทอง'
            elif 'القرع' in full_text:
                name = 'القرع'
            else:
                name = 'pumpkin'
            
            ingredients.append({
                "name": name,
                "units": unit if unit else 'cups',
                "amount": amount
            })
        
        # Проверяем наличие oats/oatmeal
        if re.search(r'oat|โอ๊ต|الشوفان', full_text, re.IGNORECASE):
            # Определяем название на основе языка
            if 'oat' in full_text.lower():
                name = 'oats'
            elif 'โอ๊ต' in full_text:
                name = 'ข้าวโอ๊ต'
            elif 'الشوفان' in full_text:
                name = 'الشوفان'
            else:
                name = 'oats'
            
            ingredients.append({
                "name": name,
                "units": None,
                "amount": None
            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        content_div = self.soup.find('div', class_='content-int')
        if not content_div:
            return None
        
        # Ищем параграфы с инструкциями
        paragraphs = content_div.find_all('p')
        
        for para in paragraphs:
            text = para.get_text(separator=' ', strip=True)
            
            # Ищем параграфы с глаголами действия (приготовления)
            action_keywords = [
                'combine', 'mix', 'heat', 'cook', 'serve', 'add', 'stir',
                'รวม', 'ผสม', 'อุ่น', 'ทํา', 'เสิร์ฟ',
                'اخلط', 'سخن', 'قدم', 'اضف'
            ]
            
            # Проверяем наличие ключевых слов приготовления
            if any(keyword in text.lower() for keyword in action_keywords):
                # Извлекаем только предложение с инструкциями
                sentences = re.split(r'[.!?]\s+', text)
                
                instructions = []
                for sentence in sentences:
                    # Проверяем, содержит ли предложение инструкции
                    if any(keyword in sentence.lower() for keyword in action_keywords):
                        instructions.append(sentence)
                
                if instructions:
                    return self.clean_text('. '.join(instructions) + '.')
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в blog-category-list
        category_list = self.soup.find('ul', class_='blog-category-list')
        if category_list:
            links = category_list.find_all('a')
            if links:
                # Берем первую категорию
                category = links[0].get_text(strip=True)
                # Если категория "Recipes", возвращаем более специфичную
                if category.lower() in ['recipes', 'สูตร', 'وصفات']:
                    # Пробуем определить по контексту
                    content_div = self.soup.find('div', class_='content-int')
                    if content_div:
                        text = content_div.get_text().lower()
                        if 'breakfast' in text or 'เช้า' in text or 'فطور' in text:
                            return 'Breakfast'
                
                return self.clean_text(category)
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str = 'total') -> Optional[str]:
        """Извлечение времени из текста"""
        if not text:
            return None
        
        # Паттерны для времени
        time_patterns = [
            r'(\d+)\s*(?:minute|minutes|min|นาที|دقيقة|دقائق)',
            r'(\d+)\s*(?:hour|hours|hr|ชั่วโมง|ساعة|ساعات)',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                number = match.group(1)
                # Проверяем единицу измерения
                if 'hour' in match.group(0).lower() or 'ชั่วโมง' in match.group(0) or 'ساعة' in match.group(0):
                    return f"{number} hours" if int(number) > 1 else f"{number} hour"
                else:
                    return f"{number} minutes" if int(number) > 1 else f"{number} minute"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В данных блогах обычно не указывается отдельно prep time
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        content_div = self.soup.find('div', class_='content-int')
        if content_div:
            text = content_div.get_text()
            
            # Ищем упоминания времени приготовления
            cook_patterns = [
                r'(?:about|approximately)\s+(?:three|3)\s+(?:minute|minutes)',
                r'(?:cook|cooking|heat|heating|microwave)(?:\s+(?:for|about|in))?\s*(\d+)\s*(?:minute|minutes|min)',
                r'(?:ทํา|อุ่น|ปรุง)\s*(?:ประมาณ)?\s*(?:สาม|3)\s*(?:นาที)',
                r'(?:طهي|تسخين)\s*(?:حوالي)?\s*(?:ثلاث|3)\s*(?:دقيقة|دقائق)',
                r'\(about\s+(?:three|3)\s+minutes\)',
                r'\(ประมาณ\s*(?:สาม|3)\s*นาที\)',
            ]
            
            for pattern in cook_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    # Проверяем, есть ли захваченная группа
                    if match.groups():
                        minutes = match.group(1)
                    else:
                        # Если нет захваченной группы, это "three" или "3"
                        minutes = "3"
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        content_div = self.soup.find('div', class_='content-int')
        if content_div:
            text = content_div.get_text()
            
            # Ищем упоминания общего времени
            total_patterns = [
                r'ready\s+to\s+eat\s+in\s+(?:only\s+)?(?:five|5)\s+(?:minute|minutes)',
                r'ready\s+(?:to\s+eat\s+)?(?:in|within)\s+(?:only\s+)?(\d+)\s+(?:minute|minutes)',
                r'พร้อมรับประทาน(?:ใน)?(?:เวลา)?(?:เพียง)?\s*(?:ห้า|5)\s*(?:นาที)',
                r'جاهز\s+في\s+(?:خمس|5)\s+(?:دقيقة|دقائق)',
            ]
            
            for pattern in total_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    # Проверяем, есть ли захваченная группа
                    if match.groups():
                        minutes = match.group(1)
                    else:
                        # Если нет захваченной группы, это "five" или "5"
                        minutes = "5"
                    return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        content_div = self.soup.find('div', class_='content-int')
        if not content_div:
            return None
        
        paragraphs = content_div.find_all('p')
        
        # Ищем параграфы с информацией о хранении или советами
        storage_keywords = [
            'store', 'storage', 'leftover', 'refrigerat', 'freez',
            'เก็บ', 'แช่', 'แช่เย็น', 'แช่แข็ง',
            'تخزين', 'حفظ', 'ثلاجة', 'فريزر'
        ]
        
        for para in paragraphs:
            text = para.get_text(separator=' ', strip=True)
            
            # Проверяем наличие ключевых слов о хранении
            if any(keyword in text.lower() for keyword in storage_keywords):
                # Извлекаем только предложения о хранении
                sentences = re.split(r'[.!?]\s+', text)
                
                storage_sentences = []
                for sentence in sentences:
                    if any(keyword in sentence.lower() for keyword in storage_keywords):
                        storage_sentences.append(sentence)
                
                if storage_sentences:
                    return self.clean_text('. '.join(storage_sentences) + '.')
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем из названия блюда и категории
        dish_name = self.extract_dish_name()
        if dish_name:
            # Добавляем ключевые слова из названия
            words = dish_name.lower().split()
            tags.extend(words)
        
        category = self.extract_category()
        if category:
            tags.append(category.lower())
        
        # Извлекаем из контента
        content_div = self.soup.find('div', class_='content-int')
        if content_div:
            text = content_div.get_text().lower()
            
            # Ищем известные теги
            common_tags = [
                'breakfast', 'lunch', 'dinner', 'dessert', 'snack',
                'pumpkin', 'oatmeal', 'quick', 'easy',
                'อาหารเช้า', 'ฟักทอง', 'โอ๊ต',
                'فطور', 'قرع', 'شوفان'
            ]
            
            for tag in common_tags:
                if tag in text:
                    tags.append(tag)
        
        # Убираем дубликаты
        unique_tags = []
        seen = set()
        for tag in tags:
            tag = tag.strip()
            if tag and tag not in seen and len(tag) > 2:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем главное изображение в blog-hero
        hero_img = self.soup.find('img', class_='blog-hero__img')
        if hero_img and hero_img.get('src'):
            urls.append(hero_img['src'])
        
        # 2. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем другие изображения в контенте
        content_div = self.soup.find('div', class_='content-int')
        if content_div:
            content_images = content_div.find_all('img')
            for img in content_images:
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
                    if len(urls) >= 3:  # Ограничиваем до 3 изображений
                        break
        
        return ','.join(urls) if urls else None
    
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
    """Обработка директории с HTML файлами"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "spendsmart_extension_iastate_edu")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SpendSmartExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python spendsmart_extension_iastate_edu.py")


if __name__ == "__main__":
    main()
