"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
from pathlib import Path
import sqlalchemy

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.embedding import get_embedding_function_bge_m3, get_embedding_function_multilingual, get_content_types
from src.stages.vectorise.vectorise import RecipeVectorizer
from src.common.db.qdrant import QdrantRecipeManager

def add_recipes(model_prefix: str = "ml-e5-large", site_id: int = None):
    if model_prefix == "bge-m3" or model_prefix == "bge-m3-nonorm":
        embed_func, dims = get_embedding_function_bge_m3()
    else:
        embed_func, dims = get_embedding_function_multilingual()

    db = MySQlManager()
    qm = QdrantRecipeManager(collection_prefix=model_prefix)
    rv = RecipeVectorizer(vector_db=qm, page_database=db)
    if not rv.connect():
        print("cant connect to dbs")
        return
    
    rv.add_all_recipes(
        embedding_function=embed_func,
        batch_size=8,
        dims=dims,
        site_id=site_id
    )

def save_similar_to_db(db: MySQlManager, model_prefix: str, similar_to_id: int, similar_results: list, content_type: str = "full"):
    """
    Сохранение похожих рецептов в БД
    
    Args:
        model_prefix: Префикс модели (ml-e5-large или bge-m3)
        similar_to_id: ID исходного рецепта
        similar_results: Список кортежей (score, Page)
    """
    table_name = model_prefix
    
    if not similar_results or len(similar_results) == 0:
        print("Нет результатов для сохранения")
        return 0
    
    print(f"Сохранение {len(similar_results)} результатов в таблицу `{table_name}`...")
    
    saved_count = 0
    
    try:
        session = db.get_session()
        for score, similar_page in similar_results:
            # Пропускаем сам рецепт
            if similar_page.id == similar_to_id:
                continue
            
            try:
                session.execute(
                    sqlalchemy.text(f"""
                        INSERT INTO `{table_name}` 
                        (similar_to, url, language, step_by_step, 
                            dish_name, description, tags, ingredient, score, content_type)
                        VALUES 
                        (:similar_to, :url, :language, :step_by_step,
                            :dish_name, :description, :tags, :ingredient, :score, :content_type)
                        ON DUPLICATE KEY UPDATE 
                            score = VALUES(score),
                            step_by_step = VALUES(step_by_step),
                            dish_name = VALUES(dish_name),
                            description = VALUES(description),
                            tags = VALUES(tags),
                            ingredient = VALUES(ingredient)
                    """),
                    {
                        "similar_to": similar_to_id,
                        "url": similar_page.url[-191:],
                        "language": similar_page.language,
                        "step_by_step": similar_page.step_by_step,
                        "dish_name": similar_page.dish_name,
                        "description": similar_page.description,
                        "tags": similar_page.tags,
                        "ingredient": similar_page.ingredient,
                        "score": float(score),
                        "content_type": content_type
                    }
                )
                saved_count += 1

            except Exception as e:
                print(f"Ошибка сохранения рецепта ID {similar_page.id}: {e}")
                import traceback
                traceback.print_exc()
        session.commit()
        session.close()
        print(f"Итого сохранено {saved_count} похожих рецептов в таблицу `{table_name}`\n")
        return saved_count
        
    except Exception as e:
        print(f"Критическая ошибка при сохранении в `{table_name}`: {e}")
        import traceback
        traceback.print_exc()
        return 0

def search_similar(model_prefix: str = "ml-e5-large", save_to_db: bool = True, recipe_id: str = "21427"):
    if model_prefix == "bge-m3":
        embed_func, _ = get_embedding_function_bge_m3()
    else:
        embed_func, _ = get_embedding_function_multilingual()

    db = MySQlManager()
    qm = QdrantRecipeManager(collection_prefix=model_prefix)
    rv = RecipeVectorizer(vector_db=qm, page_database=db)
    if not rv.connect():
        print("Не удалось подключиться к БД")
        return
    
    page = db.get_page_by_id(recipe_id)
    if not page:
        print(f"Рецепт с ID {recipe_id} не найден")
        rv.close()
        return
    
    print(f"\n{'='*60}")
    print(f"Модель: {model_prefix}")
    print(f"Поиск похожих рецептов для: {page.dish_name or page.title} (ID: {page.id})")
    print(f"{'='*60}\n")

    content_types = get_content_types()
    
    for content_type in content_types:
        print(f"\n--- Content type: {content_type} ---")
        results = rv.get_similar_recipes_as_pages(
            page=page,
            embed_function=embed_func,
            content_type=content_type,
            limit=5,
            score_threshold=0.0
        )
        
        print(f"Найдено {len(results)} похожих рецептов:")
        for score, similar_page in results:
            print(f"  Score: {score:.4f} | ID: {similar_page.id} | {similar_page.dish_name or similar_page.title}")
        
        # Сохраняем результаты в БД
        if save_to_db and len(results) > 0:
            save_similar_to_db(
                db=db, 
                model_prefix=model_prefix,
                similar_to_id=page.id,
                similar_results=results,
                content_type=content_type
            )

    rv.close()

if __name__ == '__main__':
    # Векторизация рецептов (запускать один раз)
    add_recipes(model_prefix="ml-e5-large")
    add_recipes(model_prefix="bge-m3")
    
    # Поиск похожих с сохранением в БД
    search_similar(model_prefix="ml-e5-large", save_to_db=True)
    search_similar(model_prefix="bge-m3", save_to_db=True)

    """
    что выгодного
    
    """
