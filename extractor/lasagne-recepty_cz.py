"""
Экстрактор данных рецептов для сайта lasagne-recepty.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LasagneReceptyExtractor(BaseRecipeExtractor):
    """Экстрактор для lasagne-recepty.cz"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в navigator - там обычно короткое название
        nav_current = self.soup.find('span', id='navCurrentPage')
        if nav_current:
            text = nav_current.get_text(strip=True)
            text = self.clean_text(text)
            # Возвращаем как есть, без изменения регистра
            return text
        
        # Альтернативно ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            # Убираем HTML теги вроде <u>, берем текст
            text = h1.get_text(strip=True)
            # Убираем префикс "Recept na " если есть
            text = re.sub(r'^Recept na\s+', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        Примеры:
        - "balíček lasagní" -> {name: "lasagní", units: "balíček", amount: 1}
        - "250g krájených rajčat" -> {name: "krájených rajčat", units: "g", amount: 250}
        - "50g parmazánu" -> {name: "parmazánu", units: "g", amount: 50}
        - "1 lžička plnotučná hořčice" -> {name: "plnotučná hořčice", units: "lžička", amount: 1}
        - "sůl a mletý pepř" -> {name: "sůl", units: null, amount: null} (разбиваем на два)
        """
        if not text:
            return None
        
        text = self.clean_text(text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Варианты: "250g masa", "1 lžička", "balíček lasagní", "2 stroužky česneku"
        # Формат: [количество][единица] название или [количество] [единица] название
        pattern = r'^([\d\s,.-]+)?\s*([a-zA-ZčšřžýáíéúůťďňěĚŠČŘŽÝÁÍÉÚŮĎŤŇ]+)?\s*(.+)?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Определяем единицы измерения (Czech units)
        czech_units = {
            'g', 'kg', 'ml', 'l', 'ks', 'balíček', 'konzerva', 'svazek', 
            'lžíce', 'lžička', 'lžic', 'stroužky', 'stroužek', 'stružek'
        }
        
        # Обработка количества и единицы
        amount = None
        final_unit = None
        final_name = name if name else ""
        
        # Проверяем, является ли второе слово единицей измерения
        if unit and unit.lower() in czech_units:
            final_unit = unit.lower()
            if amount_str:
                # Убираем возможные диапазоны типа "250 - 300"
                amount_str = amount_str.strip()
                # Берем первое число из диапазона
                amount_match = re.search(r'(\d+)', amount_str)
                if amount_match:
                    amount = amount_match.group(1)
            else:
                # Если нет числа, но есть единица (например "balíček lasagní")
                amount = "1"
        elif amount_str:
            # Число есть, но следующее слово может быть не единицей
            # Проверяем паттерн "250g masa" (число слитно с единицей)
            combined = amount_str.strip() + (unit if unit else "")
            unit_match = re.match(r'([\d,.-]+)\s*([a-zA-Zčšřžýáíéúůťďňě]+)', combined, re.IGNORECASE)
            if unit_match:
                amount = unit_match.group(1).replace(',', '.')
                potential_unit = unit_match.group(2).lower()
                if potential_unit in czech_units:
                    final_unit = potential_unit
                else:
                    # Единица не распознана, это часть названия
                    final_name = (unit if unit else "") + " " + (name if name else "")
            else:
                # Просто число без единицы
                amount = amount_str.strip().replace(',', '.')
                final_name = (unit if unit else "") + " " + (name if name else "")
        else:
            # Нет числа, первое слово - это часть названия
            final_name = (unit if unit else "") + " " + (name if name else "")
        
        # Очистка названия
        final_name = final_name.strip()
        if not final_name:
            final_name = text
        
        # Преобразуем amount в int или float, если возможно
        final_amount = None
        if amount:
            try:
                # Сначала пробуем int
                if '.' not in amount and ',' not in amount:
                    final_amount = int(amount)
                else:
                    final_amount = float(amount.replace(',', '.'))
            except (ValueError, AttributeError):
                final_amount = amount
        
        return {
            "name": final_name,
            "units": final_unit,
            "amount": final_amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все заголовки с "Ingredience"
        # На странице могут быть несколько секций ингредиентов
        
        # 1. Находим все <h3> заголовки содержащие "Ingredience" в тексте
        all_h3 = self.soup.find_all('h3')
        ingredient_headers = []
        for h3 in all_h3:
            text = h3.get_text(strip=True)
            if 'Ingredience' in text or 'ingredience' in text:
                ingredient_headers.append(h3)
        
        # 2. Также ищем <p><strong> заголовки (например "Špenátová náplň", "Tvarohová náplň")
        # которые могут быть после основных ингредиентов
        content = self.soup.find('div', id='content')
        if content:
            # Ищем все <p> которые содержат только <strong>
            all_p = content.find_all('p')
            for p in all_p:
                strong = p.find('strong')
                if strong:
                    text = strong.get_text(strip=True)
                    # Если это похоже на заголовок секции ингредиентов (náplň = начинка)
                    if 'náplň' in text.lower() or 'ingredience' in text.lower():
                        ingredient_headers.append(p)
        
        # Обрабатываем все найденные заголовки
        for header in ingredient_headers:
            # Находим следующий <ul> после заголовка
            ul = header.find_next('ul')
            if ul:
                items = ul.find_all('li')
                for item in items:
                    # Получаем текст ингредиента
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if not ingredient_text:
                        continue
                    
                    # Обрабатываем особые случаи типа "sůl a mletý pepř" (два ингредиента)
                    if ' a ' in ingredient_text.lower():
                        # Разбиваем на части
                        parts = re.split(r'\s+a\s+', ingredient_text, flags=re.IGNORECASE)
                        for part in parts:
                            parsed = self.parse_ingredient_text(part)
                            if parsed:
                                ingredients.append(parsed)
                    else:
                        parsed = self.parse_ingredient_text(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем заголовок с "Postup přípravy" или "Postup"
        all_h3 = self.soup.find_all('h3')
        postup_header = None
        for h3 in all_h3:
            text = h3.get_text(strip=True)
            if 'Postup' in text and ('přípravy' in text or 'postup' in text.lower()):
                postup_header = h3
                break
        
        if postup_header:
            # Собираем все параграфы после заголовка до следующего заголовка
            steps = []
            current = postup_header.find_next_sibling()
            
            while current:
                # Останавливаемся на следующем заголовке
                if current.name in ['h1', 'h2', 'h3', 'h4']:
                    break
                
                if current.name == 'p':
                    text = current.get_text(strip=True)
                    text = self.clean_text(text)
                    # Пропускаем пустые параграфы и &nbsp;
                    if text and text != '\xa0' and text != ' ':
                        steps.append(text)
                
                current = current.find_next_sibling()
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории - для lasagne всегда Main Course"""
        # Все рецепты на этом сайте - это lasagne, которые являются основным блюдом
        return "Main Course"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций паттерны типа "45 minut", "40 minut", "30 minut"
        instructions_text = self.extract_instructions()
        if instructions_text:
            # Паттерн: "zapékáme 20 - 30 minut" - берем основное время запекания
            # Не суммируем с "dalších X minut" т.к. это дополнительное время для другого шага
            zapekame_pattern = re.search(r'zapékáme\s+(?:asi\s+)?(\d+)\s*-?\s*(\d+)?\s*minut', instructions_text, re.IGNORECASE)
            if zapekame_pattern:
                # Если есть диапазон, берем второе число (максимум)
                if zapekame_pattern.group(2):
                    minutes = int(zapekame_pattern.group(2))
                else:
                    minutes = int(zapekame_pattern.group(1))
                return f"{minutes} minutes"
            
            # Если нет "zapékáme", ищем просто время в конце инструкций
            all_times = re.findall(r'(\d+)\s*-?\s*(\d+)?\s*minut', instructions_text, re.IGNORECASE)
            if all_times:
                last_time = all_times[-1]
                minutes = last_time[1] if last_time[1] else last_time[0]
                return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте время подготовки не указывается отдельно
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте общее время не указывается отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем предложения с "Místo", "můžeme použít" и подобными
        instructions_text = self.extract_instructions()
        if instructions_text:
            # Разбиваем на предложения
            sentences = re.split(r'[.!?]\s+', instructions_text)
            notes = []
            for sentence in sentences:
                # Ищем фразы, указывающие на заметку/совет
                if 'místo' in sentence.lower() and 'můžeme' in sentence.lower():
                    # Это скорее всего заметка о замене ингредиента
                    notes.append(sentence.strip())
            
            if notes:
                return '. '.join(notes) + '.'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Добавляем тип из названия блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            dish_lower = dish_name.lower()
            
            # Определяем тип lasagne
            if 'špenát' in dish_lower:
                tags.append("lasagne")
                tags.append("špenát")
                tags.append("italská kuchyně")
            elif 'rajčat' in dish_lower:
                tags.append("lasagne")
                tags.append("rajčatové")
                tags.append("italské")
            elif 'tradiční' in dish_lower:
                tags.append("italian")
                tags.append("lasagne")
                tags.append("main course")
            else:
                # Базовый случай
                tags.append("lasagne")
                tags.append("main course")
        else:
            # Если нет названия, базовые теги
            tags.append("lasagne")
            tags.append("main course")
        
        return ', '.join(tags)
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем изображение в illustration div
        illustration = self.soup.find('div', id='illustration')
        if illustration:
            img = illustration.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 2. Ищем изображения внутри content области (в h3 или других местах)
        content = self.soup.find('div', id='content')
        if content:
            imgs = content.find_all('img')
            for img in imgs:
                if img.get('src'):
                    src = img['src']
                    # Пропускаем маленькие иконки и уже добавленные
                    if src not in urls and not src.endswith('.svg') and not src.endswith('.ico'):
                        urls.append(src)
        
        # Ограничиваем до разумного количества (например, 5)
        if urls:
            return ','.join(urls[:5])
        
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
    # Обрабатываем папку preprocessed/lasagne-recepty_cz
    recipes_dir = os.path.join("preprocessed", "lasagne-recepty_cz")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LasagneReceptyExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python lasagne-recepty_cz.py")


if __name__ == "__main__":
    main()
