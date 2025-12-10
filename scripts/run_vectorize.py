"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.embedding import get_embedding_function_bge_m3, prepare_text
from src.stages.vectorise.vectorise import RecipeVectorizer
from src.common.db.qdrant import QdrantRecipeManager

def add_recipes():
    db = MySQlManager()
    qm = QdrantRecipeManager(collection_prefix="bge-m3")
    rv = RecipeVectorizer(vector_db=qm, page_database=db)
    if not rv.connect():
        print("cant connect to dbs")
        return
    
    pages = rv.get_pages(limit=2000)

    embed_func, dims = get_embedding_function_bge_m3()
    qm.create_collections(colbert_dim=dims, dense_dim=dims)
    addedd = qm.add_recipes(pages=pages, embedding_function=embed_func, batch_size=8)
    print(f"Всего добавлено: {addedd}/{len(pages)}")
    qm.close()

def search_similar():
    db = MySQlManager()
    qm = QdrantRecipeManager(collection_prefix="bge-m3")
    rv = RecipeVectorizer(vector_db=qm, page_database=db)
    if not rv.connect():
        print("cant connect to dbs")
        return
    
    embed_func, dims = get_embedding_function_bge_m3()
    qm.create_collections(colbert_dim=dims, dense_dim=dims)

    page = rv.get_pages(limit=1)[0]
    print("Ищем похожие на страницу:")
    print(f"{page.id} - {page.dish_name}")
    query_text = prepare_text(page, embedding_type="full")
    results = qm.search(
        query_text=query_text,
        embedding_function=embed_func,
        limit=6,
        embedding_type="full"
    )

    for data in results:
        print("Результаты поиска:")
        print("---------------")
        print(f"name: {data['dish_name']}")
        print(f"   [{data['score']:.2f}] {data['page_id']} lang {data['language']}...")

    qm.close()

if __name__ == '__main__':
    #add_recipes()
    search_similar()

"""
TODO:
1. Создать 1 коллекцию - полныйы текст (не понятно ка кделить огромный текст, который размывается, его по-хорошему надо резать на части, но при этом теряем целостнотсь рецепта)
2. Создать 2 коллекцию - несколько ветокров в коллеции отдельно по описанию тегам и тд

3. Попробовать поиск с разным эмбедингом для всех таких коллекций (попробовать bgem3 для этой ситуации и попробвоать intfloat/multilingual-e5-large )
"""