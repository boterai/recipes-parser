"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.embedding import get_embedding_function, EmbeddingFunction
from src.stages.vectorise.vectorise import RecipeVectorizer
from src.models.page import Page
import sqlalchemy
from typing import Optional


def vectorize_all_recipes(db: MySQlManager, vectorizer: RecipeVectorizer, limit: Optional[int] = None, batch_size: Optional[int] = 100, site_id: Optional[int] = None):
    """
    Векторизация всех рецептов из БД
    
    Args:
        db: Менеджер базы данных
        limit: Ограничение количества рецептов (None = все)
        batch_size: Размер батча для обработки
        site_id: ID сайта для фильтрации
    """

    
    with db.get_session() as session:
        # Получаем рецепты из БД
        sql = """
            SELECT * FROM pages 
            WHERE is_recipe = TRUE 
            AND dish_name IS NOT NULL
            AND ingredients IS NOT NULL
        """
        
        if site_id:
            sql += f" AND site_id != {site_id}"

        if limit:
            sql += f" LIMIT {limit}"
        
        result = session.execute(sqlalchemy.text(sql))
        rows = result.fetchall()
        pages = [Page.model_validate(dict(row._mapping)) for row in rows]
        
        print(f"\n{'=' * 60}")
        print(f"Найдено {len(pages)} рецептов для векторизации")
        print(f"{'=' * 60}\n")
        
        # Добавляем батчами
        total_added = 0
        for i in range(0, len(pages), batch_size):
            batch = pages[i:i + batch_size]
            added = vectorizer.add_recipes_batch(batch)
            total_added += added
            progress = min(i + batch_size, len(pages))
            print(f"Прогресс: {progress}/{len(pages)} ({progress * 100 / len(pages):.1f}%)")
        
        print(f"\n{'=' * 60}")
        print("✓ Векторизация завершена!")
        print(f"  Всего добавлено: {total_added}/{len(pages)}")
        print(f"{'=' * 60}\n")
    
def search_examples(vectorizer: RecipeVectorizer, db: MySQlManager):
    """Search examples"""
    print(f"\n{'=' * 60}")
    print("SEARCH EXAMPLES")
    print(f"{'=' * 60}\n")
    
    # 1. Simple search
    print("1. Search: 'fast dessert with apples'")
    results = vectorizer.search("fast dessert with apples", n_results=3)
    for r in results:
        page = db.get_page_by_id(int(r['page_id']))
        print(f"   Dish Name: {page.dish_name if page else 'N/A'}")
        print(f"   [{r['score']:.2f}] {r['page_id']} - {page.description[:50]}...")
    
    # 2. Search in ingredients collection
    print("\n2. Search in ingredients: 'chicken, rice, vegetables'")
    results = vectorizer.search("chicken, rice, vegetables", n_results=3, collection_name="ingredients")
    for r in results:
        page = db.get_page_by_id(int(r['page_id']))
        print(f"   Dish Name: {page.dish_name if page else 'N/A'}")
        print(f"   [{r['score']:.2f}] {r['page_id']} - {page.description[:50]}...")
    
    # 3. Search in instructions collection
    print("\n3. Search in instructions: 'bake in oven'")
    results = vectorizer.search("bake in oven", n_results=3, collection_name="instructions")
    for r in results:
        page = db.get_page_by_id(int(r['page_id']))
        print(f"   Dish Name: {page.dish_name if page else 'N/A'}")
        print(f"   [{r['score']:.2f}] {r['page_id']} - {page.description[:50]}...")
    
    # 4. Search in descriptions
    print("\n4. Search in descriptions: 'easy quick meal'")
    results = vectorizer.search("easy quick meal", n_results=3, collection_name="descriptions")
    for r in results:
        page = db.get_page_by_id(int(r['page_id']))
        print(f"   Dish Name: {page.dish_name if page else 'N/A'}")
        print(f"   [{r['score']:.2f}] {r['page_id']} - {page.description[:50]}...")

    print("\nSearch similar recipes to a given recipe:")
    # 5. Search similar recipes to a given recipe
    sample_page_id = 106  # Пример ID страницы
    sample_page = db.get_page_by_id(sample_page_id)
    if sample_page:
        print(f"\n5. Similar recipes to: {sample_page.dish_name}")
        results = vectorizer.search(sample_page.dish_name + " " + sample_page.ingredients, n_results=3)
        for r in results:
            page = db.get_page_by_id(int(r['page_id']))
            print(f"   Dish Name: {page.dish_name if page else 'N/A'}")
            print(f"   [{r['score']:.2f}] {r['page_id']} - {page.description[:50]}...")


def main():
    lim = None  # Ограничение количества рецептов (None = все)
    db = MySQlManager()
    if not db.connect():
        print("Не удалось подключиться к базе данных")
        return
    
    # Устанавливаем функцию эмбеддингов
    print("Загрузка модели эмбеддингов...")
    embedding_func, embedding_dim = get_embedding_function()
    print("✓ Модель загружена\n")
    
    # Векторизация
    vectorizer = RecipeVectorizer(embedding_dim=embedding_dim)
    if vectorizer.connect() is False:
        print("Не удалось подключиться к векторной базе данных")
        return
    
    vectorizer.set_embedding_function(embedding_func)
    vectorize_all_recipes(db, vectorizer=vectorizer, site_id=1, limit=lim)
    
    # Примеры поиска
    search_examples(vectorizer, db)


if __name__ == '__main__':
    main()