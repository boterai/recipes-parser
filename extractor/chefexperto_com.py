"""
Экстрактор данных рецептов для сайта chefexperto.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ChefExpertoExtractor(BaseRecipeExtractor):
    """Экстрактор для chefexperto.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text().strip()
            # Убираем лишние фразы типа "Receta de", "Paso a Paso", "Cómo Preparar", и т.д.
            title = re.sub(r'^Receta\s+de\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r':\s*Paso\s+a\s+Paso.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r':\s*Cómo\s+Preparar.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+para\s+el\s+Plato\s+Español.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+Tradicional$', '', title, flags=re.IGNORECASE)
            title = self.clean_text(title)
            return title if title else None
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'^Receta\s+de\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем первый значимый параграф в контенте
        for p in self.soup.find_all('p'):
            text = p.get_text().strip()
            # Проверяем что это описательный текст (достаточно длинный и содержит ключевые слова)
            if text and len(text) > 50 and len(text) < 300:
                # Проверяем наличие ключевых слов для описания рецепта
                if any(kw in text.lower() for kw in ['plato', 'receta', 'tradicional', 'cocina', 'español', 'clásico']):
                    # Берем только первое предложение
                    sentences = text.split('.')
                    if sentences:
                        first_sentence = sentences[0].strip() + '.'
                        return self.clean_text(first_sentence)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        found_basic = False
        processed_sections = set()
        
        # Ищем заголовок с "Ingredientes" или "Elementos Básicos"
        for h3 in self.soup.find_all(['h3', 'h2']):
            h3_text = h3.get_text().strip()
            
            # Пропускаем уже обработанные секции
            if h3_text in processed_sections:
                continue
            
            # Проверяем различные варианты заголовков для основных ингредиентов
            if any(kw in h3_text for kw in ['Ingredientes básicos', 'Ingredientes Necesarios', 'Elementos Básicos']):
                # Берем только первую секцию с ингредиентами
                if not found_basic:
                    # Получаем следующий ul список
                    next_ul = h3.find_next('ul')
                    if next_ul:
                        items = next_ul.find_all('li')
                        for item in items:
                            # Извлекаем текст ингредиента
                            text = item.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            
                            if text:
                                # Парсим ингредиент
                                parsed = self.parse_ingredient(text)
                                if parsed and parsed['name']:
                                    # Проверяем на дубликаты по имени
                                    if not any(ing['name'] == parsed['name'] for ing in ingredients):
                                        ingredients.append(parsed)
                        
                        found_basic = True
                        processed_sections.add(h3_text)
            
            # Также проверяем для дополнительных секций (приправы, соусы)
            elif found_basic and any(kw in h3_text for kw in ['Condimentos', 'Aderezos', 'Condimentos y Aderezos']):
                next_ul = h3.find_next('ul')
                if next_ul:
                    items = next_ul.find_all('li')
                    for item in items:
                        text = item.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            parsed = self.parse_ingredient(text)
                            if parsed and parsed['name']:
                                # Проверяем на дубликаты
                                if not any(ing['name'] == parsed['name'] for ing in ingredients):
                                    ingredients.append(parsed)
                    processed_sections.add(h3_text)
        
        # Если не нашли по стандартным заголовкам, пробуем найти хоть что-то
        if not ingredients:
            for h3 in self.soup.find_all(['h3', 'h2']):
                h3_text = h3.get_text().strip().lower()
                if 'ingredientes' in h3_text:
                    next_ul = h3.find_next('ul')
                    if next_ul:
                        items = next_ul.find_all('li')
                        for item in items:
                            text = item.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                parsed = self.parse_ingredient(text)
                                if parsed and parsed['name']:
                                    if not any(ing['name'] == parsed['name'] for ing in ingredients):
                                        ingredients.append(parsed)
                        if ingredients:
                            break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Формат chefexperto: "Название: Описание" или просто "Название"
        
        Returns:
            dict: {"name": "...", "amount": None, "units": None}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Разделяем по двоеточию если есть
        if ':' in text:
            # Формат: "Patatas: Opta por patatas de calidad..."
            name_part = text.split(':', 1)[0].strip()
        else:
            # Просто название
            name_part = text
        
        # Извлекаем только название (удаляем количества если есть в начале)
        # Пример: "200g patatas" -> "patatas"
        name_match = re.match(r'^(?:\d+[\s\d./]*(?:g|kg|ml|l|unidades?|tazas?|cucharadas?)?\s+)?(.+)', name_part, re.IGNORECASE)
        if name_match:
            name = name_match.group(1).strip()
        else:
            name = name_part
        
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        
        # Ищем заголовок с "Pasos" или "Preparación"
        for h3 in self.soup.find_all(['h3', 'h2']):
            h3_text = h3.get_text().strip()
            if any(kw in h3_text for kw in ['Pasos para la Preparación', 'Pasos', 'Elaboración', 'Método']):
                # Ищем следующий ul или ol список
                next_list = h3.find_next(['ul', 'ol'])
                if next_list:
                    items = next_list.find_all('li')
                    for item in items:
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text and len(step_text) > 20:  # Только значимые шаги
                            steps.append(step_text)
                    
                    if steps:
                        break
        
        # Если список шагов не найден, ищем по другим заголовкам
        if not steps:
            for h3 in self.soup.find_all(['h3', 'h2']):
                h3_text = h3.get_text().strip()
                # Ищем заголовки, связанные с процессом приготовления
                if any(kw in h3_text for kw in ['El Sofrito', 'Incorporación', 'Cocción', 'Preparación']):
                    # Берем параграфы, которые описывают шаги
                    current = h3.find_next_sibling()
                    count = 0
                    while current and count < 3:  # Максимум 3 параграфа
                        if current.name == 'h3':
                            break
                        if current.name == 'p':
                            text = current.get_text().strip()
                            text = self.clean_text(text)
                            if text and len(text) > 30:
                                # Берем только первое предложение из параграфа
                                sentences = text.split('.')
                                if sentences:
                                    step = sentences[0].strip() + '.'
                                    if step not in steps:
                                        steps.append(step)
                                        count += 1
                        current = current.find_next_sibling()
                    
                    if steps:
                        break
        
        # Если все еще не нашли шагов, попробуем извлечь из параграфов с глаголами действия
        if not steps:
            # Ищем параграфы, которые содержат инструкции (начинаются с глаголов)
            instruction_verbs = ['pelar', 'cortar', 'freír', 'batir', 'mezclar', 'cocinar', 'colocar', 
                               'sofreír', 'añadir', 'incorporar', 'seleccionar']
            for p in self.soup.find_all('p'):
                text = p.get_text().strip()
                text = self.clean_text(text)
                if text:
                    # Проверяем начало текста на наличие глаголов действия
                    first_word = text.split()[0].lower() if text.split() else ''
                    if any(verb in first_word for verb in instruction_verbs):
                        # Берем все предложение
                        sentences = text.split('.')
                        if sentences:
                            for sentence in sentences[:2]:  # Первые 2 предложения
                                s = sentence.strip()
                                if s and len(s) > 15:
                                    steps.append(s + '.')
                        if len(steps) >= 3:
                            break
        
        # Форматируем и возвращаем шаги
        if steps:
            # Нумеруем шаги если еще не пронумерованы
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в мета-тегах
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Проверяем URL на наличие категории
        # Например: /espana/receta-de-...
        for link in self.soup.find_all('link', rel='canonical'):
            url = link.get('href', '')
            if '/espana/' in url.lower():
                return 'Main Course'
        
        # По умолчанию для основных блюд
        return 'Main Course'
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени по метке
        
        Args:
            time_label: 'preparación', 'cocción', 'total'
        """
        # Ищем в тексте паттерны времени
        content = self.soup.get_text()
        
        # Паттерны для поиска времени
        patterns = [
            rf'{time_label}[^\d]*?(\d+)\s*(minuto|hora|min|h)',
            rf'tiempo\s+de\s+{time_label}[^\d]*?(\d+)\s*(minuto|hora|min|h)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                number, unit = matches[0]
                # Нормализуем единицу
                if 'hora' in unit or unit == 'h':
                    # Конвертируем часы в минуты
                    minutes = int(number) * 60
                    return f"{minutes} minutes"
                else:
                    return f"{number} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('preparación')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self.extract_time('cocción')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем заголовки с ключевыми словами о качестве, советах, техниках
        keywords = ['calidad', 'consejo', 'técnica', 'perfecto', 'secreto', 'tip', 'nota']
        
        for h3 in self.soup.find_all(['h3', 'h2', 'h4']):
            h3_text = h3.get_text().strip().lower()
            if any(kw in h3_text for kw in keywords):
                # Получаем следующий параграф или список
                next_elem = h3.find_next(['p', 'ul'])
                if next_elem:
                    if next_elem.name == 'p':
                        text = next_elem.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text and len(text) > 20:
                            notes.append(text)
                    elif next_elem.name == 'ul':
                        items = next_elem.find_all('li')
                        for item in items:
                            text = item.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                notes.append(text)
        
        if notes:
            # Объединяем все заметки
            return ' '.join(notes[:3])  # Берем первые 3 заметки
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в мета-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если нет в мета-тегах, генерируем из названия блюда
        if not tags:
            dish_name = self.extract_dish_name()
            if dish_name:
                # Разбиваем название на слова и берем основные
                words = dish_name.lower().split()
                # Фильтруем короткие слова
                tags = [w for w in words if len(w) > 3]
                # Добавляем базовые теги
                tags.extend(['español', 'receta'])
        
        if tags:
            # Удаляем дубликаты
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            return ', '.join(unique_tags[:10])  # Максимум 10 тегов
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url.startswith('http'):
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if script.string:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        # Ищем image в Article или другом типе
                        if 'image' in data:
                            img = data['image']
                            if isinstance(img, dict) and 'url' in img:
                                url = img['url']
                                if url and url.startswith('http') and url not in urls:
                                    urls.append(url)
                            elif isinstance(img, str) and img.startswith('http'):
                                if img not in urls:
                                    urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в теге img в контенте
        for img in self.soup.find_all('img', src=True):
            src = img['src']
            if src and src.startswith('http') and 'chefexperto.com' in src:
                # Фильтруем логотипы и иконки
                if not any(skip in src.lower() for skip in ['logo', 'icon', 'avatar', 'cropped']):
                    if src not in urls:
                        urls.append(src)
                        if len(urls) >= 3:  # Ограничиваем до 3 изображений
                            break
        
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
    """Обработка HTML файлов из директории preprocessed/chefexperto_com"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "chefexperto_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ChefExpertoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python chefexperto_com.py")


if __name__ == "__main__":
    main()
