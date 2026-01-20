"""
Экстрактор данных рецептов для сайта cozinhatradicional.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CozinhaTradicionalExtractor(BaseRecipeExtractor):
    """Экстрактор для cozinhatradicional.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта с классом wprm-fallback-recipe-name
        recipe_header = self.soup.find('h2', class_='wprm-fallback-recipe-name')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из основного заголовка страницы
        main_header = self.soup.find('h1', class_='title entry-title')
        if main_header:
            return self.clean_text(main_header.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в wprm-fallback-recipe-summary (приоритет)
        summary_p = self.soup.find('p', class_='wprm-fallback-recipe-summary')
        
        if summary_p:
            # Проверяем, есть ли текст в этом параграфе
            text = self.clean_text(summary_p.get_text())
            if not text or len(text) < 10:
                # Если пустой, ищем следующий параграф-сиблинг
                next_p = summary_p.find_next_sibling('p')
                if next_p:
                    summary_p = next_p
            
            text = self.clean_text(summary_p.get_text())
            if text:
                # Убираем вводные фразы типа "Experimente [название блюда], [описание]"
                match = re.search(r'Experimente\s+[^,]+,\s*(.+)', text, flags=re.IGNORECASE)
                if match:
                    text = match.group(1)
                
                # Убираем восклицательный знак в конце и добавляем точку
                text = text.rstrip('!').rstrip('.')
                if text:
                    return text + '.'
        
        # Альтернативно - в div с классом wprm-fallback-recipe-summary
        summary_div = self.soup.find('div', class_='wprm-fallback-recipe-summary')
        if summary_div:
            p_tag = summary_div.find('p')
            if p_tag:
                text = self.clean_text(p_tag.get_text())
                if text:
                    match = re.search(r'Experimente\s+[^,]+,\s*(.+)', text, flags=re.IGNORECASE)
                    if match:
                        text = match.group(1)
                    text = text.rstrip('!').rstrip('.')
                    if text:
                        return text + '.'
        
        # Ищем в основном тексте первый параграф с описанием
        content_div = self.soup.find('div', class_='nv-content-wrap')
        if content_div:
            for p in content_div.find_all('p'):
                text = self.clean_text(p.get_text())
                # Фильтруем параграфы с заголовками или очень короткие
                if text and len(text) > 50 and not text.endswith(':'):
                    # Проверяем, что это не начало с инструкций
                    if not any(text.lower().startswith(prefix) for prefix in ['use ', 'para ', 'em uma', 'em outra', 'você pode', 'mistura']):
                        # Извлекаем основное описание
                        match = re.search(r'é\s+(.+)', text, re.IGNORECASE)
                        if match:
                            desc = match.group(1).strip().rstrip('.').rstrip('!')
                            return desc + '.'
                        return text
        
        # В крайнем случае - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 pacote de massa para lasanha" или "500 ml de leite"
            
        Returns:
            dict: {"name": "massa para lasanha", "amount": 1, "units": "pacote"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Убираем скобочные пояснения для упрощения парсинга, но сохраняем оригинал для имени
        text_for_parsing = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 pacote de massa", "500 ml de leite", "2 colheres de sopa de azeite"
        # Базовые единицы измерения
        units_pattern = r'(?:pacotes?|latas?|unidades?|unidade|dentes?|colheres?(?:\s+de\s+sopa)?(?:\s+de\s+chá)?|colher(?:\s+de\s+sopa)?(?:\s+de\s+chá)?|ml|g|kg|litros?|liter|l)'
        
        # Паттерн: число + единица + de + название
        pattern = rf'^(\d+(?:[.,]\d+)?)\s+({units_pattern})\s+(?:de\s+)?(.+)'
        match = re.match(pattern, text_for_parsing, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            # Конвертируем amount в число
            try:
                amount = int(amount_str) if '.' not in amount_str and ',' not in amount_str else float(amount_str.replace(',', '.'))
            except ValueError:
                amount = amount_str
            
            # Очистка названия от лишних слов
            name = re.sub(r'\s+(a gosto|quanto baste|picad[oa]s?|ralad[oa]s?)$', '', name, flags=re.IGNORECASE).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.strip()
            }
        
        # Паттерн без единицы измерения (только количество + название)
        # Например: "2 cebolas", "3 ovos"  
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(.+)'
        match2 = re.match(pattern2, text_for_parsing)
        
        if match2:
            amount_str, name = match2.groups()
            # Конвертируем amount в число
            try:
                amount = int(amount_str) if '.' not in amount_str and ',' not in amount_str else float(amount_str.replace(',', '.'))
            except ValueError:
                amount = amount_str
            
            # Очистка названия
            name = re.sub(r'\s+(a gosto|quanto baste|picad[oa]s?|ralad[oa]s?)$', '', name, flags=re.IGNORECASE).strip()
            
            # Если есть слово "de" в середине, возможно это единица измерения
            # Например: "1 colher de sopa de salsinha" -> units="colher de sopa", name="salsinha"
            unit_match = re.match(r'^(colher(?:es)?\s+de\s+(?:sopa|chá))\s+(?:de\s+)?(.+)', name, re.IGNORECASE)
            if unit_match:
                unit, name = unit_match.groups()
                return {
                    "name": name.strip(),
                    "amount": amount,
                    "units": unit.strip()
                }
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если нет количества (например, "sal a gosto", "sal e pimenta-do-reino a gosto")
        name = re.sub(r'\s+(a gosto|quanto baste)$', '', text_for_parsing, flags=re.IGNORECASE).strip()
        
        # Убираем артикли и предлоги в начале
        name = re.sub(r'^(?:o|a|os|as|de|do|da|dos|das)\s+', '', name).strip()
        
        if name and len(name) > 1:
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find('div', class_='wprm-fallback-recipe-ingredients')
        
        if ingredients_container:
            # Извлекаем элементы списка (ul > li)
            items = ingredients_container.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_container = self.soup.find('div', class_='wprm-fallback-recipe-instructions')
        
        if instructions_container:
            # Извлекаем элементы списка (ol > li)
            step_items = instructions_container.find_all('li')
            
            current_section = []
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Проверяем, является ли это заголовком секции (короткий текст, заканчивается двоеточием)
                    is_section_header = step_text.endswith(':') and len(step_text) < 30
                    
                    if is_section_header:
                        # Сохраняем накопленный текст предыдущей секции
                        if current_section:
                            steps.append(' '.join(current_section))
                        # Начинаем новую секцию с заголовка
                        current_section = [step_text]
                    else:
                        # Добавляем к текущей секции
                        current_section.append(step_text)
            
            # Добавляем последнюю секцию
            if current_section:
                steps.append(' '.join(current_section))
        
        # Объединяем все секции
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в wprm-fallback-recipe-meta-course
        course_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-course')
        if course_meta:
            text = self.clean_text(course_meta.get_text())
            if text:
                # Может содержать несколько значений через запятую
                # Берем последнее значение, которое обычно является основной категорией
                parts = [p.strip() for p in text.split(',') if p.strip()]
                if parts:
                    # Ищем "Prato Principal" или подобные
                    for part in reversed(parts):
                        if any(word in part.lower() for word in ['prato', 'course', 'main', 'principal']):
                            return part
                    # Если не нашли специфичную категорию, возвращаем последнюю
                    return parts[-1]
        
        # Альтернативно - из meta articleSection
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return self.clean_text(article_section['content'])
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в мета-данных рецепта
        cook_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-cook-time')
        if cook_time_meta:
            return self.clean_text(cook_time_meta.get_text())
        
        # Пытаемся извлечь из инструкций (ищем все упоминания времени и суммируем)
        instructions_text = self.extract_instructions()
        if instructions_text:
            # Ищем все паттерны типа "30 minutos", "10 minutes"
            time_matches = re.findall(r'(\d+)\s*(?:minutos?|minutes?)', instructions_text, re.IGNORECASE)
            if time_matches:
                total_minutes = sum(int(m) for m in time_matches)
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в мета-данных рецепта
        prep_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-prep-time')
        if prep_time_meta:
            return self.clean_text(prep_time_meta.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в мета-данных рецепта
        total_time_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-total-time')
        if total_time_meta:
            return self.clean_text(total_time_meta.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секции с заметками после основного контента рецепта
        # Обычно это блоки с strong заголовками
        content_div = self.soup.find('div', class_='nv-content-wrap')
        
        if content_div:
            # Ищем все параграфы со strong внутри
            for p in content_div.find_all('p'):
                strong = p.find('strong')
                if strong:
                    strong_text = self.clean_text(strong.get_text())
                    # Проверяем, что это похоже на заголовок совета (заканчивается двоеточием)
                    if strong_text and ':' in strong_text:
                        # Извлекаем текст после strong (основной текст заметки)
                        # Получаем весь текст параграфа
                        full_text = self.clean_text(p.get_text())
                        # Убираем заголовок из текста
                        note_text = full_text.replace(strong_text, '').strip()
                        
                        if note_text:
                            # Убираем лишние слова-связки
                            note_text = re.sub(r'\bportanto\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bem suma\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bpor isso\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bassim\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            # Очищаем от множественных пробелов
                            note_text = re.sub(r'\s+', ' ', note_text).strip()
                            notes.append(note_text)
                
                # Также проверяем следующий элемент - может быть ul список с заметками
                next_elem = p.find_next_sibling()
                if strong and next_elem and next_elem.name == 'ul' and 'wp-block-list' in next_elem.get('class', []):
                    for li in next_elem.find_all('li'):
                        note_text = self.clean_text(li.get_text())
                        if note_text:
                            # Убираем лишние слова-связки
                            note_text = re.sub(r'\bportanto\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bem suma\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bpor isso\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\bassim\b,?\s*', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'^Opte\s+', '', note_text, flags=re.IGNORECASE)
                            note_text = re.sub(r'\s+', ' ', note_text).strip()
                            if note_text and not any(skip in note_text.lower() for skip in ['melhores panelas', 'melhores fornos', 'melhores fogões']):
                                notes.append(note_text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в wprm-fallback-recipe-meta-keyword
        keyword_meta = self.soup.find('div', class_='wprm-fallback-recipe-meta-keyword')
        if keyword_meta:
            text = self.clean_text(keyword_meta.get_text())
            if text:
                # Теги уже разделены запятыми
                return text
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item and item['url'] not in urls:
                                urls.append(item['url'])
                            elif 'contentUrl' in item and item['contentUrl'] not in urls:
                                urls.append(item['contentUrl'])
                        
                        # Article/WebPage с image
                        if item.get('@type') in ['Article', 'WebPage'] and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict):
                                img_url = img.get('@id') or img.get('url') or img.get('contentUrl')
                                if img_url and img_url not in urls:
                                    urls.append(img_url)
                            elif isinstance(img, str) and img not in urls:
                                urls.append(img)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ограничиваем до 3 изображений и возвращаем как строку через запятую
        if urls:
            unique_urls = []
            for url in urls:
                if url and url not in unique_urls:
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
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
    import os
    # Обрабатываем папку preprocessed/cozinhatradicional_com
    recipes_dir = os.path.join("preprocessed", "cozinhatradicional_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CozinhaTradicionalExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cozinhatradicional_com.py")


if __name__ == "__main__":
    main()
