# Recipe Parser

Парсер рецептов с кулинарных сайтов с использованием Selenium и ChatGPT API.



## Запуск

```bash
# Запустить Chrome с отладкой
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug_9222
```

## скрипты 
1. scripts/prepare_site - генерация запросов для поиска в duck duck go, поиск сайтов, анализ сайтов, генерация примеров для создания парсера
2. scripts/parse - парсинг сайтов (для которых есть парсеры в extractor директории) в один или несколкьо потоков
3. scripts/translate - перевод страниц с рецептами и доабвление их в clickhouse
4. scripts/vectorise - поиск похожих и векторизация данных (пока без изображений)
5. scripts/search - поиск похожих в clickhouse по рецептам и по запросу


Ошибка парсинга JSON от GPT: Expecting ',' delimiter: line 1 column 1716 (char 1715)
2026-01-19 13:35:09,237 - ERROR - Ответ GPT: {"dish_name": "Chicken Noodle Soup with Omelette", "description": "This soup pairs well with lightly salted pickles and pickled garlic.", "ingredients": ["500 g chicken thighs on the bone", "1 medium carrot", "1 medium onion", "4 cloves of garlic", "1 small bunch of parsley or dill", "150 g egg noodles", "2 eggs", "1 tbsp butter or vegetable oil", "0.5 tsp whole black peppercorns", "0.5 tsp whole allspice berries", "salt, freshly ground black pepper"], "tags": ["soup", "chicken soup", "noodle soup", "chicken thighs"], "category": "soup", "instructions": "step 1: Rub the chicken thighs with salt, place in a pot, cover with 2 liters of cold water. Bring to a boil over high heat. Reduce the heat to a simmer. Skim off any foam. step 2: Thoroughly scrub the onion and carrot without peeling. Cut in half lengthwise. Dry roast in a pan without oil until charred. Crush the garlic cloves with the flat side of a knife. Trim the stems from the herbs, wash them well (set aside the leaves). step 3: Add all prepared vegetables and herb stems to the broth. Add the black and allspice berries and a little salt. Simmer, uncovered, for 2 hours. step 4: Finely chop the herb leaves. Whisk the eggs with a pinch of salt. Add 2 tsp of herbs. Heat a skillet over medium heat, melt the butter. Pour in the eggs and cook the omelette. The eggs should be fully cooked. Transfer the omelette to a cutting board, let it cool, then slice into thin strips. step 5: Remove the chicken thighs from the broth with a slotted spoon, cut the meat off the bones. Strain the broth into a clean pot. Add the chicken meat. Bring the broth to a boil again, add the noodles, cook according to the package instructions. Divide the omelette "noodles" among bowls, pour the soup with egg noodles and chicken meat. Sprinkle with the remaining herbs and serve.", "cook_time": "150 minutes", "prep_time": "", "total_time": "150 minutes"}