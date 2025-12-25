import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.search.clickhouse_search import SearchSimilarInClickhouse
from src.models.recipe import Recipe

def print_recipe_list(recipes: list[tuple[float, Recipe]]):
    for score, recipe in recipes:
        print(f"Score {score} Recipe ID: {recipe.page_id}, Title: {recipe.dish_name}")
        print("Ingredients:", recipe.ingredients)
        print("-----")

def main(search_type: int = 2):
    ss = SearchSimilarInClickhouse()

    match search_type:
        case 0:
            result: list[tuple[float, Recipe]] = ss.search_recipe_regex_by_text_query(text_query="roast duck with honey sauce", limit=20)
            print_recipe_list(result)
        case 1:

            result: list[tuple[float, Recipe]] = ss.full_recipe_regex_search(ingredients=["duck", "honey", ".*"],
                                                                            description=["swee.*", "deli.*"], limit=20)
            print_recipe_list(result)
        case 2:

            result: list[tuple[float, Recipe]] = ss.search_recipes_by_text_query(
                text_query="roast duck with honey sauce",
                limit=20
            )
            print_recipe_list(result)

        case 3:

            # поиск по ингредиентам
            result: list[tuple[float, Recipe]] = ss.search_recipes_by_ingredients(ingredients=["duck", "honey"], limit=20)
            print_recipe_list(result)

if __name__ == "__main__":
    main(2)
