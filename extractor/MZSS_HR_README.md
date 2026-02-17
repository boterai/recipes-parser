# mzss.hr Recipe Extractor

## Overview
Parser для извлечения рецептов с сайта mzss.hr.

## Структура данных

Экстрактор извлекает следующие поля:

- **dish_name**: Название блюда (из h3 заголовка с id вида "1-название-рецепта" или из title страницы)
- **description**: Описание (из JSON-LD BlogPosting или meta description)
- **ingredients**: JSON-массив ингредиентов с полями name/amount/units
- **instructions**: Инструкции приготовления (текст из ol.wp-block-list)
- **category**: Категория (из meta property="article:section")
- **prep_time**: Время подготовки (обычно None, нет в HTML)
- **cook_time**: Время приготовления (извлекается из текста инструкций, например "15 minutes")
- **total_time**: Общее время (обычно None, нет в HTML)
- **notes**: Заметки (параграф после инструкций, если есть)
- **tags**: Теги (из meta property="article:tag", разделены ", ")
- **image_urls**: URL изображений (из og:image и twitter:image, разделены ",")

## Использование

### Командная строка

```bash
python extractor/mzss_hr.py
```

Обработает все HTML файлы из директории `preprocessed/mzss_hr/`.

### Программный вызов

```python
from extractor.mzss_hr import MzssHrExtractor

# Создание экстрактора
extractor = MzssHrExtractor('/path/to/recipe.html')

# Извлечение всех данных
data = extractor.extract_all()

# Извлечение отдельных полей
dish_name = extractor.extract_dish_name()
ingredients = extractor.extract_ingredients()
instructions = extractor.extract_instructions()
```

## Особенности реализации

### Структура страниц mzss.hr

Страницы mzss.hr часто содержат НЕСКОЛЬКО рецептов в одной статье. Парсер извлекает данные **первого** рецепта, который имеет:

1. Заголовок h3 с id, начинающимся с цифры (например, `id="1-pecena-brokula-s-parmezanom"`)
2. Параграф с текстом "Sastojci:"
3. Список ингредиентов (ul.wp-block-list)
4. Параграф с текстом "Priprema:"
5. Список инструкций (ol.wp-block-list)

### Парсинг ингредиентов

Ингредиенты парсятся из строк формата:
- `"1 velika glavica brokule"` → `{name: "brokule", amount: "1", units: "velika glavica"}`
- `"2 žlice maslinovog ulja"` → `{name: "maslinovog ulja", amount: "2", units: "žlice"}`
- `"sol i crni papar"` → `{name: "sol i crni papar", amount: null, units: null}`
- `"3 češnja češnjaka, sitno sjeckana"` → `{name: "češnjaka", amount: "3", units: "češnja"}`

Поддерживаются единицы измерения:
- Хорватские: velika glavica, glavica, žlice, žličica, šalice, češnja, gram (g), kilogram (kg), litar (l), mililitar (ml)
- Английские: cup, tablespoon (tbsp), teaspoon (tsp), clove, head

### Очистка данных

- Из названий ингредиентов удаляются описания после запятой (например, ", sitno sjeckana")
- Из текста удаляются фразы "po izboru", "po želji" и содержимое в скобках
- Из amount берется первое число при указании диапазона (например, "15-20" → "15")

## Тестирование

```bash
# Запуск тестов
python -m unittest tests.extractor.test_mzss_hr -v

# Должны пройти все 12 тестов
```

## Примеры

### Пример 1: Простой рецепт

HTML:
```html
<h3 id="1-pecena-brokula-s-parmezanom">1. Pečena brokula s parmezanom</h3>
<p>Sastojci:</p>
<ul class="wp-block-list">
  <li>1 velika glavica brokule</li>
  <li>2 žlice maslinovog ulja</li>
</ul>
<p>Priprema:</p>
<ol class="wp-block-list">
  <li>Zagrijte pećnicu na 200°C.</li>
  <li>Operite brokulu...</li>
</ol>
```

Output:
```json
{
  "dish_name": "Pečena brokula s parmezanom",
  "ingredients": "[{\"name\": \"brokule\", \"amount\": \"1\", \"units\": \"velika glavica\"}, ...]",
  "instructions": "Zagrijte pećnicu na 200°C. Operite brokulu...",
  ...
}
```

## Известные ограничения

1. Некоторые страницы mzss.hr содержат статьи о здоровье с рецептами в тексте, но без структурированных секций "Sastojci:" и "Priprema:". В таких случаях парсер может не найти ингредиенты и инструкции.

2. Названия ингредиентов остаются в той форме, в которой они указаны в HTML (например, в родительном падеже: "brokule", "maslinovog ulja"), а не приводятся к именительному падежу.

3. Время приготовления (prep_time, cook_time, total_time) извлекается из текста инструкций, если упоминается, или остается None. В HTML нет структурированных данных для времени.

4. Некоторые поля (например, category) берутся из мета-тегов статьи (article:section) и могут не соответствовать специфической категории рецепта (например, "Prehrana" вместо "Main Course").
