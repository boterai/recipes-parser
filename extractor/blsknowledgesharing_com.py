"""
Экстрактор данных рецептов для сайта blsknowledgesharing.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BlsknowledgesharingExtractor(BaseRecipeExtractor):
    """Экстрактор для blsknowledgesharing.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пытаемся извлечь из Q&A секции (самое точное название)
        faq_items = self.soup.find_all('div', class_='faq-item')
        
        for faq_item in faq_items:
            question = faq_item.find('h3', class_='chatgin-question')
            if not question:
                continue
            
            question_text = question.get_text()
            
            # Ищем первое упоминание блюда в кавычках
            match = re.search(r'["\']([^"\']+)["\']', question_text)
            if match:
                dish = match.group(1)
                # Удаляем лишние кавычки
                dish = dish.strip('"\'')
                if dish and len(dish) < 50:  # Разумная длина для названия блюда
                    return self.clean_text(dish)
        
        # Если не найдено в Q&A, пробуем из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Извлекаем название до первой вертикальной черты или тире
            match = re.match(r'^([^|–\-]+)', title)
            if match:
                title = match.group(1)
            # Удаляем кавычки и лишние пробелы
            title = re.sub(r'["\']', '', title)
            title = re.sub(r'\s*을\s*집에서.*', '', title)
            title = re.sub(r'\s*를\s*집에서.*', '', title)
            title = re.sub(r'\s*-\s*지식공유.*$', '', title)
            title = self.clean_text(title)
            if title:
                return title
        
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
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: строка вида "2 cups flour" или "flour"
            
        Returns:
            Dict с ключами: name, amount, units
        """
        ingredient_text = self.clean_text(ingredient_text)
        if not ingredient_text:
            return None
        
        # Попытка парсинга с количеством и единицами
        # Формат: "число единица название" или "число название"
        patterns = [
            # С единицами измерения (например, "2.5 컵 고운 밀가루")
            r'^([\d.]+)\s*([가-힣a-zA-Z]+)\s+(.+)$',
            # Только число (например, "2 소금")
            r'^([\d.]+)\s+(.+)$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, ingredient_text)
            if match:
                if len(match.groups()) == 3:
                    amount, units, name = match.groups()
                    return {
                        "name": self.clean_text(name),
                        "units": self.clean_text(units),
                        "amount": float(amount) if '.' in amount else int(amount)
                    }
                elif len(match.groups()) == 2:
                    amount, name = match.groups()
                    return {
                        "name": self.clean_text(name),
                        "units": None,
                        "amount": float(amount) if '.' in amount else int(amount)
                    }
        
        # Если не удалось распарсить, возвращаем просто название
        return {
            "name": ingredient_text,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients_from_qa(self) -> Optional[str]:
        """Извлечение ингредиентов из секции Q&A"""
        ingredients = []
        
        # Ищем секцию FAQ/Q&A
        faq_items = self.soup.find_all('div', class_='faq-item')
        
        for faq_item in faq_items:
            question = faq_item.find('h3', class_='chatgin-question')
            answer = faq_item.find('p', class_='chatgin-answer')
            
            if not question or not answer:
                continue
            
            question_text = question.get_text()
            
            # Проверяем, содержит ли вопрос упоминание о ингредиентах/재료
            if '재료' in question_text or '필수 재료' in question_text:
                # Получаем HTML для более точной обработки
                answer_html = str(answer)
                
                # Разбиваем по <br> тегам для получения строк
                lines = re.split(r'<br\s*/?>', answer_html)
                
                for line in lines:
                    # Удаляем HTML теги
                    line = re.sub(r'<[^>]+>', '', line)
                    line = line.strip()
                    
                    # Удаляем маркеры списка
                    line = re.sub(r'^[–•\-*]\s*', '', line)
                    # Пропускаем заголовки и короткие строки
                    if not line or line.startswith('A.') or line.startswith('🌟') or '🌟' in line or len(line) < 3:
                        continue
                    
                    # Не разделяем по запятым внутри скобок (например, "생선 (예 참치, 연어)")
                    # Сначала проверяем наличие скобок
                    if '(' in line and ')' in line:
                        # Обрабатываем как один ингредиент
                        line = self.clean_text(line)
                        if line:
                            parsed = self.parse_ingredient(line)
                            if parsed:
                                ingredients.append(parsed)
                    else:
                        # Разделяем по запятым только если нет скобок
                        parts = re.split(r',\s*', line)
                        for part in parts:
                            part = self.clean_text(part)
                            if part and not part.startswith('🌟'):
                                parsed = self.parse_ingredient(part)
                                if parsed:
                                    ingredients.append(parsed)
        
        if not ingredients:
            return None
        
        return json.dumps(ingredients, ensure_ascii=False)
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        # Сначала пробуем извлечь из Q&A секции
        qa_ingredients = self.extract_ingredients_from_qa()
        if qa_ingredients:
            return qa_ingredients
        
        return None
    
    def extract_instructions_from_qa(self) -> Optional[str]:
        """Извлечение инструкций из секции Q&A"""
        # Ищем секцию FAQ/Q&A
        faq_items = self.soup.find_all('div', class_='faq-item')
        
        for faq_item in faq_items:
            question = faq_item.find('h3', class_='chatgin-question')
            answer = faq_item.find('p', class_='chatgin-answer')
            
            if not question or not answer:
                continue
            
            question_text = question.get_text()
            
            # Проверяем, содержит ли вопрос упоминание о способе приготовления
            # Но НЕ о ингредиентах (чтобы не путать с ingredients)
            if ('조리법' in question_text or '만드는 방법' in question_text) and '재료' not in question_text:
                answer_text = answer.get_text()
                
                # Очищаем текст от заголовков типа "A. 🌟단순 조리법🌟"
                answer_text = re.sub(r'^A\.\s*🌟[^🌟]*🌟\s*', '', answer_text)
                answer_text = self.clean_text(answer_text)
                
                if answer_text and len(answer_text) > 10:
                    return answer_text
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Сначала пробуем извлечь из Q&A
        qa_steps = self.extract_instructions_from_qa()
        if qa_steps:
            return qa_steps
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Попробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в данных Article
                if isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list) and sections:
                                    # Возвращаем первую секцию, если это не про автомойку
                                    for section in sections:
                                        if section and section != '출장세차':
                                            return self.clean_text(section)
                                elif isinstance(sections, str):
                                    if sections and sections != '출장세차':
                                        return self.clean_text(sections)
            except:
                continue
        
        # Возвращаем значение по умолчанию
        return "Main Course"
    
    def extract_time_from_qa(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из секции Q&A
        
        Args:
            time_type: тип времени ('준비', 'prep', '조리', 'cook', '전체', 'total')
        """
        # Ищем секцию FAQ/Q&A
        faq_items = self.soup.find_all('div', class_='faq-item')
        
        for faq_item in faq_items:
            question = faq_item.find('h3', class_='chatgin-question')
            answer = faq_item.find('p', class_='chatgin-answer')
            
            if not question or not answer:
                continue
            
            question_text = question.get_text()
            answer_text = answer.get_text()
            
            # Проверяем упоминание времени в вопросе или ответе
            if '시간' in question_text or '시간' in answer_text:
                # Ищем паттерны времени
                patterns = [
                    r'(\d+)\s*시간\s*(\d+)?\s*분?',  # "1 시간 30 분" или "1시간"
                    r'(\d+)\s*분',  # "30 분"
                    r'(\d+)\s*hours?\s*(\d+)?\s*minutes?',  # "1 hour 30 minutes"
                    r'(\d+)\s*minutes?',  # "30 minutes"
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, answer_text)
                    if match:
                        groups = match.groups()
                        if len(groups) == 2 and groups[0] and groups[1]:
                            # Часы и минуты
                            hours = int(groups[0])
                            minutes = int(groups[1])
                            total_minutes = hours * 60 + minutes
                            return f"{total_minutes} minutes"
                        elif groups[0]:
                            # Только минуты или часы
                            value = int(groups[0])
                            if '시간' in pattern or 'hour' in pattern:
                                return f"{value * 60} minutes"
                            else:
                                return f"{value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_qa('준비')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self.extract_time_from_qa('조리')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_qa('전체')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов"""
        # Ищем секцию FAQ/Q&A с заметками или советами
        faq_items = self.soup.find_all('div', class_='faq-item')
        
        for faq_item in faq_items:
            question = faq_item.find('h3', class_='chatgin-question')
            answer = faq_item.find('p', class_='chatgin-answer')
            
            if not question or not answer:
                continue
            
            question_text = question.get_text()
            
            # Проверяем, содержит ли вопрос упоминание о советах/팁/주의
            if '팁' in question_text or '주의' in question_text or '조언' in question_text or '노트' in question_text:
                answer_text = answer.get_text()
                answer_text = re.sub(r'^A\.\s*🌟[^🌟]*🌟\s*', '', answer_text)
                answer_text = self.clean_text(answer_text)
                
                if answer_text and len(answer_text) > 10:
                    return answer_text
        
        # Альтернативно - ищем в основном контенте
        # Проверяем параграфы с подсказками
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text()
            # Ищем короткие предложения с советами о свежих ингредиентах
            if ('신선한' in text and '재료' in text and len(text) < 100) or \
               ('레시피는' in text and ('친근한' in text or '쉬' in text) and len(text) < 100):
                text = self.clean_text(text)
                if text:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Попробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем keywords в Article
                if isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    return ', '.join([self.clean_text(k) for k in keywords])
                                elif isinstance(keywords, str):
                                    return self.clean_text(keywords)
            except:
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        images = []
        
        # Проверяем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            images.append(og_image['content'])
        
        # Проверяем thumbnail URL в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article':
                                if 'thumbnailUrl' in item:
                                    url = item['thumbnailUrl']
                                    if url and url not in images:
                                        images.append(url)
                                if 'image' in item and isinstance(item['image'], dict):
                                    if 'url' in item['image']:
                                        url = item['image']['url']
                                        if url and url not in images:
                                            images.append(url)
            except:
                continue
        
        # Ограничиваем до 3 изображений (как в других парсерах)
        images = images[:3]
        
        if images:
            return ','.join(images)
        
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
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
    # Определяем путь к директории с примерами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "blsknowledgesharing_com"
    
    if preprocessed_dir.exists():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(BlsknowledgesharingExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == "__main__":
    main()
