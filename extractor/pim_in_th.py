"""
Экстрактор данных рецептов для сайта pim.in.th
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PimInThExtractor(BaseRecipeExtractor):
    """Экстрактор для pim.in.th"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h2 с itemprop="name"
        title_elem = self.soup.find('h2', itemprop='name')
        if title_elem:
            # Внутри h2 есть <a> с текстом
            link = title_elem.find('a', itemprop='url')
            if link:
                return self.clean_text(link.get_text())
            return self.clean_text(title_elem.get_text())
        
        # Альтернативно из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из articleBody"""
        article_body = self.soup.find('div', itemprop='articleBody')
        if not article_body:
            return None
        
        ingredients = []
        
        # Ищем параграф с маркером ингредиентов
        all_paragraphs = article_body.find_all('p')
        
        ingredient_section_found = False
        for i, p in enumerate(all_paragraphs):
            text = p.get_text().strip()
            
            # Проверяем различные маркеры начала секции ингредиентов
            # Маркер должен быть в начале строки или обрамлен в ::
            is_ingredient_section = False
            if text.startswith(':: สิ่งที่ต้องเตรียม') or text.startswith(':: ส่วนผสม'):
                is_ingredient_section = True
            
            if is_ingredient_section:
                ingredient_section_found = True
                # Следующий параграф обычно содержит ингредиенты
                if i + 1 < len(all_paragraphs):
                    next_p = all_paragraphs[i + 1]
                    ingredients_text = next_p.get_text(separator='\n')
                    
                    # Разбиваем по переносам строк и обрабатываем каждую строку
                    lines = ingredients_text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and line.startswith('-'):
                            # Парсим ингредиент
                            parsed = self.parse_ingredient_thai(line[1:].strip())
                            if parsed:
                                ingredients.append(parsed)
                    break
        
        if not ingredients:
            return None
        
        return json.dumps(ingredients, ensure_ascii=False)
    
    def parse_ingredient_thai(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента на тайском языке в структурированный формат
        
        Args:
            ingredient_text: Строка вида "วุ้นเส้น 80 กรัม" или "น้ำมะนาว 1/4 ถ้วย"
            
        Returns:
            dict: {"name": "วุ้นเส้น", "amount": "80", "unit": "กรัม"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем комментарии в скобках для извлечения основной информации
        text_no_parens = re.sub(r'\([^)]*\)', '', text)
        
        # Тайские единицы измерения
        # กรัม (грамм), ถ้วย (чашка), ช้อนโต๊ะ (столовая ложка), ช้อนชา (чайная ложка),
        # ชต. (сокращение), มล. (мл), กก. (кг)
        units_pattern = r'(กรัม|ถ้วย|ช้อนโต๊ะ|ช้อนชา|ชต\.|มล\.|กก\.|ลิตร|มิลลิลิตร|กิโลกรัม|ออนซ์|ปอนด์|ฟอง|ใบ|ต้น|เม็ด|ชิ้น|แท่ง)'
        
        # Паттерн для числа (может быть дробь или десятичное число)
        number_pattern = r'([\d\./]+|\d+\s*\+\s*\d+/\d+)'
        
        # Общий паттерн: [название] [количество] [единица]
        # Пример: วุ้นเส้น 80 กรัม
        pattern = rf'^(.+?)\s+({number_pattern})\s+({units_pattern}).*$'
        
        match = re.match(pattern, text_no_parens)
        
        if match:
            name = match.group(1).strip()
            amount_str = match.group(2).strip()
            unit = match.group(4).strip()
            
            # Обработка количества - конвертируем дроби
            amount = self.parse_amount(amount_str)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def parse_amount(self, amount_str: str) -> Optional[str]:
        """Парсинг количества (может быть дробь типа "1/2" или "2 + 1/2")"""
        if not amount_str:
            return None
        
        amount_str = amount_str.strip()
        
        # Обработка случая "2 + 1/2" (число + дробь)
        if '+' in amount_str:
            parts = amount_str.split('+')
            total = 0
            for part in parts:
                part = part.strip()
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num.strip()) / float(denom.strip())
                else:
                    total += float(part)
            return str(total)
        
        # Обработка дроби "1/2"
        if '/' in amount_str:
            num, denom = amount_str.split('/')
            return str(float(num.strip()) / float(denom.strip()))
        
        # Обычное число
        return amount_str
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        article_body = self.soup.find('div', itemprop='articleBody')
        if not article_body:
            return None
        
        instructions = []
        
        # Ищем параграф с маркером инструкций
        all_paragraphs = article_body.find_all('p')
        
        instruction_section_found = False
        for i, p in enumerate(all_paragraphs):
            text = p.get_text().strip()
            
            # Проверяем различные маркеры начала секции инструкций
            # Маркер должен быть в начале строки или обрамлен в ::
            is_instruction_section = False
            if text.startswith(':: วิธีทำ') or text.startswith(':: การทำ'):
                is_instruction_section = True
            
            if is_instruction_section:
                instruction_section_found = True
                # Собираем все следующие параграфы до конца или до следующей секции
                for j in range(i + 1, len(all_paragraphs)):
                    next_p = all_paragraphs[j]
                    para_text = next_p.get_text(separator=' ', strip=True)
                    para_text = self.clean_text(para_text)
                    
                    # Пропускаем параграфы с изображениями (пустые после очистки)
                    if not para_text or len(para_text) < 10:
                        continue
                    
                    # Останавливаемся на следующей секции (если есть)
                    if para_text.strip().startswith('::'):
                        break
                    
                    # Добавляем текст инструкции
                    instructions.append(para_text)
                
                break
        
        if not instructions:
            return None
        
        # Объединяем все инструкции в одну строку
        return ' '.join(instructions)
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в <a itemprop="genre">
        category_elem = self.soup.find('a', itemprop='genre')
        if category_elem:
            return self.clean_text(category_elem.get_text())
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta keywords"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разбиваем по запятой и фильтруем
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            # Возвращаем первые несколько тегов (без мусорных общих слов)
            return ', '.join(tags[:10]) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах (og:image - главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Если URL относительный, делаем его абсолютным
            if url and not url.startswith('http'):
                url = 'https://www.pim.in.th' + url
            urls.append(url)
        
        # 2. Ищем изображения в articleBody
        article_body = self.soup.find('div', itemprop='articleBody')
        if article_body:
            images = article_body.find_all('img')
            for img in images:
                src = img.get('src')
                if src:
                    # Делаем URL абсолютным если нужно
                    if not src.startswith('http'):
                        src = 'https://www.pim.in.th' + src
                    urls.append(src)
        
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
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и дополнительной информации"""
        article_body = self.soup.find('div', itemprop='articleBody')
        if not article_body:
            return None
        
        notes = []
        
        # Ищем параграфы с выделенным текстом (em, italic)
        # Обычно примечания оформлены курсивом
        em_paragraphs = article_body.find_all('p')
        
        for p in em_paragraphs:
            # Проверяем наличие <em> внутри параграфа
            em_elem = p.find('em')
            if em_elem:
                text = em_elem.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text and len(text) > 10:
                    # Убираем маркер "***" если есть
                    text = text.replace('***', '').strip()
                    notes.append(text)
        
        if notes:
            return ' ... '.join(notes)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки - в pim.in.th обычно нет структурированных данных"""
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления - в pim.in.th обычно нет структурированных данных"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени - в pim.in.th обычно нет структурированных данных"""
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка всех HTML файлов в директории preprocessed/pim_in_th"""
    import os
    
    # Путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "pim_in_th"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(PimInThExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python pim_in_th.py")


if __name__ == "__main__":
    main()
