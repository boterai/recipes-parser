"""
Экстрактор данных рецептов для сайта tuja.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TujaHuExtractor(BaseRecipeExtractor):
    """Экстрактор для tuja.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта (h1)
        recipe_header = self.soup.find('h1')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Krémleves recept"
            title = re.sub(r'\s+-\s+.*$', '', title)
            return self.clean_text(title)
        
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
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в формат {name, amount, units}
        
        Args:
            line: строка типа "25 dkg kenőmájas (vagy májkrém)" или "só"
            
        Returns:
            Словарь с полями name, amount, units или None
        """
        if not line:
            return None
        
        line = line.strip().rstrip(',')
        
        # Паттерн: количество + единица + название
        # Примеры: "25 dkg kenőmájas", "1 kg burgonya", "3 tojássárga"
        # Также: "1 csomó metélőhagyma (snidling)"
        pattern = r'^([\d.,/]+)\s*(kg|dkg|g|ml|dl|l|evőkanál|teáskanál|csomag|csomó|fej|db)?(.+)$'
        match = re.match(pattern, line, re.IGNORECASE)
        
        if match:
            amount = match.group(1).strip()
            units = match.group(2).strip() if match.group(2) else None
            name = match.group(3).strip()
            
            # Удаляем дополнительные пояснения в скобках из названия
            # Но сохраняем основное название до скобок
            name = re.sub(r'\s*\([^)]*\)', '', name).strip()
            # Удаляем точки в конце
            name = name.rstrip('.')
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        else:
            # Нет количества - просто название (например, "só", "bors")
            # Удаляем пояснения в скобках
            name = re.sub(r'\s*\([^)]*\)', '', line).strip()
            name = name.rstrip('.')
            
            # Пропускаем пустые строки после очистки
            if not name:
                return None
            
            return {
                "name": name,
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        article = self.soup.find('article', id='article')
        if not article:
            return None
        
        # Ищем параграфы в статье
        paragraphs = article.find_all('p')
        
        # Ищем параграф с "hozzávalók:" (ингредиенты)
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if not text:
                continue
            
            # Ищем параграф с "hozzávalók:"
            if 'hozzávalók:' in text.lower():
                # Извлекаем часть после "hozzávalók:"
                parts = re.split(r'hozzávalók:', text, flags=re.IGNORECASE)
                
                ingredients_text = None
                
                # Случай 1: Ингредиенты в том же параграфе (после "hozzávalók:")
                if len(parts) > 1 and parts[1].strip():
                    ingredients_text = parts[1]
                # Случай 2: Ингредиенты в следующем параграфе
                elif i + 1 < len(paragraphs):
                    next_p = paragraphs[i + 1]
                    ingredients_text = next_p.get_text(strip=True)
                
                if not ingredients_text:
                    break
                
                # ВАЖНО: Останавливаемся перед маркером инструкций
                # Паттерн: "készítése :" или "elkészítés:" или ".Название készítése:"
                
                # Ищем любой из маркеров инструкций
                inst_patterns = [
                    r'\.\s*[A-ZÁÉÍÓÖŐÚÜŰ][^,]*?(készítése|elkészítése|készítés)\s*:',  # ".Название készítése :"
                    r'(készítése|elkészítése|készítés)\s*:',  # просто "készítése :"
                ]
                
                earliest_match = None
                earliest_pos = len(ingredients_text)
                
                for pattern in inst_patterns:
                    match = re.search(pattern, ingredients_text, re.IGNORECASE)
                    if match and match.start() < earliest_pos:
                        earliest_match = match
                        earliest_pos = match.start()
                
                if earliest_match:
                    # Обрезаем до начала инструкций
                    ingredients_text = ingredients_text[:earliest_pos]
                
                # Разделяем по запятым
                ingredient_lines = [line.strip() for line in ingredients_text.split(',')]
                
                for line in ingredient_lines:
                    # Пропускаем пустые строки
                    if not line:
                        continue
                    
                    # Останавливаемся на любых длинных текстах (инструкции)
                    if len(line) > 100:
                        break
                    
                    parsed = self.parse_ingredient_line(line)
                    if parsed:
                        ingredients.append(parsed)
                
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        article = self.soup.find('article', id='article')
        if not article:
            return None
        
        paragraphs = article.find_all('p')
        
        instructions_parts = []
        found_instructions_start = False
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if not text:
                continue
            
            # Начало инструкций
            if 'elkészítés' in text.lower() or 'készítése:' in text.lower() or 'készítés' in text.lower():
                found_instructions_start = True
                
                # Случай 1: Инструкции в том же параграфе (после ключевого слова)
                # Разделяем по ключевым словам
                parts = re.split(r'(elkészítés[ée]?:?|készítése:?|készítés[ée]?:)', text, flags=re.IGNORECASE)
                
                # parts будет: [текст_до, ключевое_слово, текст_после, ...]
                # Ищем текст после ключевого слова
                for j in range(len(parts)):
                    if j > 0 and re.match(r'(elkészítés|készítése|készítés)', parts[j], re.IGNORECASE):
                        # Следующая часть - это инструкции
                        if j + 1 < len(parts):
                            inst_text = parts[j + 1].strip()
                            if inst_text:
                                instructions_parts.append(inst_text)
                
                # Случай 2: Инструкции в следующих параграфах
                # Продолжаем собирать параграфы после текущего
                continue
            
            # После начала инструкций собираем все параграфы
            if found_instructions_start:
                # Останавливаемся, если нашли начало другого рецепта
                if 'hozzávalók:' in text.lower() and len(instructions_parts) > 0:
                    break
                
                # Пропускаем слишком короткие, неинформативные или другие рецепты
                if (len(text) > 20 and 
                    not text.startswith('Frissítve') and
                    not re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű\s]+Hozzávalók:', text)):
                    instructions_parts.append(text)
        
        # Объединяем все части инструкций
        if instructions_parts:
            return ' '.join(instructions_parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        article = self.soup.find('article', id='article')
        if not article:
            return None
        
        # Ищем список категорий в начале статьи
        cat_list = article.find('ul', class_='list-inline')
        if cat_list:
            links = cat_list.find_all('a')
            if links:
                # Берем первую ссылку как основную категорию
                category_text = links[0].get_text(strip=True)
                return self.clean_text(category_text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На tuja.hu нет информации о времени подготовки
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # На tuja.hu нет информации о времени готовки
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На tuja.hu нет информации о времени
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На tuja.hu нет специальной секции заметок
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # На tuja.hu нет тегов
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем извлечь из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            image_url = og_image['content']
            if image_url and not image_url.endswith('icon.png'):  # Пропускаем иконки сайта
                urls.append(image_url)
        
        # Пробуем найти изображения в статье
        article = self.soup.find('article', id='article')
        if article:
            images = article.find_all('img', limit=5)
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http') and src not in urls:
                    # Пропускаем маленькие изображения и иконки
                    if not any(skip in src for skip in ['icon', 'logo', 'avatar', 'small']):
                        urls.append(src)
        
        if urls:
            # Возвращаем в формате строки, разделенной запятыми
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
    """
    Основная функция для обработки директории с HTML-файлами tuja.hu
    """
    import os
    
    # Определяем путь к директории с preprocessed файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "tuja_hu"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(TujaHuExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Убедитесь, что директория preprocessed/tuja_hu существует")


if __name__ == "__main__":
    main()
