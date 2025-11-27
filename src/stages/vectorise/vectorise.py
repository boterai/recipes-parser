
"""
Модуль для векторизации рецептов с использованием ChromaDB.
"""

# Для чего: 
# Искать похожие рецепты и вариации на основе ингредиентов и инструкций.

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.page import Page


class RecipeVectorizer:
    """Векторизатор рецептов на основе ChromaDB с сохранением на диск"""
    
    def __init__(self, persist_directory: str = "./vector_db"):
        """
        Инициализация векторизатора
        
        Args:
            persist_directory: Путь для сохранения данных на диск
        """
        self.persist_directory = persist_directory
        
        # Создаем директорию если не существует
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        
        # Persistent клиент - данные сохраняются на диск
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(
                anonymized_telemetry=False,  # Отключаем телеметрию
                allow_reset=True
            )
        )
        metadata = {
                "hnsw:space": "cosine",  # Косинусное расстояние для текстов
                "hnsw:M": 16,  # Количество связей в графе HNSW
                "hnsw:construction_ef": 100  # Размер динамического списка при построении
            }
        
        # Создаем или получаем коллекцию
        self.collection = self.client.get_or_create_collection(
            name="recipes",
            metadata=metadata
        )

        self.ingedients_collection = self.client.get_or_create_collection(
            name="ingredients",
            metadata=metadata
        )

        self.step_by_step_collection = self.client.get_or_create_collection(
            name="step_by_step",
            metadata=metadata
        )

        self.description_collection = self.client.get_or_create_collection(
            name="descriptions",
            metadata=metadata
        )
        
        print(f"  Путь к данным: {persist_directory}")
        print(f"  Коллекция: {self.collection.name}")
        print(f"  Количество рецептов: {self.collection.count()}")
    
    def _prepare_text(self, page: Page) -> str:
        """
        Подготовка текста для создания эмбеддинга
        
        Args:
            page: Объект страницы с рецептом
            
        Returns:
            Объединенный текст для эмбеддинга
        """
        parts = []
        
        # Название блюда
        if page.dish_name:
            parts.append(page.dish_name)
        
        # Описание
        if page.description:
            parts.append(page.description)
        
        # Ингредиенты
        if page.ingredients and not page.ingredients_names:
            parts.append(f"Ingredients: {page.ingredients[:300]}")  # Ограничение по длине

        if page.ingredients_names:
            parts.append(f"Ingredient names: {page.ingredients_names}")
        
        # Заметки
        if page.notes:
            parts.append(page.notes[:100])  # Ограничение по длине
        
        return ". ".join(parts)
    
    def add_recipe(self, page: Page) -> bool:
        """
        Добавление одного рецепта в векторную БД
        
        Args:
            page: Объект страницы с рецептом
            
        Returns:
            True если успешно добавлено
        """
        try:
            # Проверяем что это рецепт
            if not page.is_recipe or not page.dish_name:
                print(f"⚠ Пропущен: не является рецептом или нет названия (ID: {page.id})")
                return False
            
            # Общие метаданные
            base_metadata = {
                "page_id": page.id,
                "site_id": page.site_id
            }
            
            # 1. Основная коллекция - полный текст
            full_text = self._prepare_text(page)
            self.collection.add(
                ids=[str(page.id)],
                documents=[full_text],
                metadatas=[base_metadata]
            )
            
            # 2. Коллекция ингредиентов
            if page.ingredients_names:
                self.ingedients_collection.add(
                    ids=[str(page.id)],
                    documents=[page.ingredients_names],
                    metadatas=[base_metadata]
                )
            
            # 3. Коллекция инструкций
            if page.step_by_step:
                # Берем первые 3 шага или 500 символов
                #steps = page.step_by_step.split('\n')[:3]
                #instructions_summary = '. '.join(steps)[:500]
                self.step_by_step_collection.add(
                    ids=[str(page.id)],
                    documents=[page.step_by_step],
                    metadatas=[base_metadata]
                )
            
            # 4. Коллекция описаний
            if page.description:
                description_text = f"{page.dish_name}. {page.description}"
                self.description_collection.add(
                    ids=[str(page.id)],
                    documents=[description_text],
                    metadatas=[base_metadata]
                )
            
            print(f"✓ Добавлен: {page.dish_name} (ID: {page.id})")
            return True
            
        except Exception as e:
            print(f"✗ Ошибка при добавлении рецепта {page.id}: {e}")
            return False
    
    def add_recipes_batch(self, pages: List[Page]) -> int:
        """
        Массовое добавление рецептов
        
        Args:
            pages: Список объектов страниц с рецептами
            
        Returns:
            Количество успешно добавленных рецептов
        """
        # Данные для основной коллекции
        main_ids = []
        main_documents = []
        main_metadatas = []
        
        # Данные для коллекции ингредиентов
        ingredient_ids = []
        ingredient_documents = []
        ingredient_metadatas = []
        
        # Данные для коллекции инструкций
        instruction_ids = []
        instruction_documents = []
        instruction_metadatas = []
        
        # Данные для коллекции описаний
        description_ids = []
        description_documents = []
        description_metadatas = []
        
        added_count = 0
        
        for page in pages:
            # Проверяем что это рецепт
            if not page.is_recipe or not page.dish_name:
                continue
            
            try:
                # Общие метаданные
                base_metadata = {
                    "page_id": page.id,
                    "site_id": page.site_id
                }
                
                # 1. Основная коллекция
                text = self._prepare_text(page)
                main_ids.append(str(page.id))
                main_documents.append(text)
                main_metadatas.append(base_metadata)
                
                # 2. Коллекция ингредиентов
                if page.ingredients_names:
                    ingredient_ids.append(str(page.id))
                    ingredient_documents.append(page.ingredients_names)
                    ingredient_metadatas.append(base_metadata)
                
                # 3. Коллекция инструкций
                if page.step_by_step:
                    #steps = page.step_by_step.split('\n')[:3]
                    #instructions_summary = '. '.join(steps)[:500]
                    instruction_ids.append(str(page.id))
                    instruction_documents.append(page.step_by_step)
                    instruction_metadatas.append(base_metadata)
                
                # 4. Коллекция описаний
                if page.description:
                    description_text = f"{page.dish_name}. {page.description}"
                    description_ids.append(str(page.id))
                    description_documents.append(description_text)
                    description_metadatas.append(base_metadata)
                
                added_count += 1
                
            except Exception as e:
                print(f"✗ Ошибка при подготовке рецепта {page.id}: {e}")
                continue
        
        # Добавляем батчами в каждую коллекцию
        try:
            if main_ids:
                self.collection.add(
                    ids=main_ids,
                    documents=main_documents,
                    metadatas=main_metadatas
                )
            
            if ingredient_ids:
                self.ingedients_collection.add(
                    ids=ingredient_ids,
                    documents=ingredient_documents,
                    metadatas=ingredient_metadatas
                )
            
            if instruction_ids:
                self.step_by_step_collection.add(
                    ids=instruction_ids,
                    documents=instruction_documents,
                    metadatas=instruction_metadatas
                )
            
            if description_ids:
                self.description_collection.add(
                    ids=description_ids,
                    documents=description_documents,
                    metadatas=description_metadatas
                )
            
            print(f"✓ Добавлено {added_count} рецептов в 4 коллекции")
            
        except Exception as e:
            print(f"✗ Ошибка при добавлении батча: {e}")
            return 0
        
        return added_count
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        site_id: Optional[int] = None,
        collection_name: str = "main"
    ) -> List[Dict[str, Any]]:
        """
        Поиск похожих рецептов
        
        Args:
            query: Поисковый запрос (текст)
            n_results: Количество результатов
            site_id: Фильтр по сайту
            collection_name: Коллекция для поиска ("main", "ingredients", "instructions", "descriptions")
            
        Returns:
            Список найденных рецептов с метаданными
        """
        # Выбираем коллекцию
        if collection_name == "ingredients":
            collection = self.ingedients_collection
        elif collection_name == "instructions":
            collection = self.step_by_step_collection
        elif collection_name == "descriptions":
            collection = self.description_collection
        else:
            collection = self.collection
        
        # Формируем фильтр
        where_filter = {}
        
        if site_id is not None:
            where_filter["site_id"] = site_id
        
        # Выполняем поиск
        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter if where_filter else None
            )
            
            # Форматируем результаты
            output = []
            if results['ids'] and results['ids'][0]:
                for i in range(len(results['ids'][0])):
                    output.append({
                        "id": results['ids'][0][i],
                        "distance": results['distances'][0][i],
                        "similarity": 1 - results['distances'][0][i],  # Косинусное сходство
                        "page_id": results['metadatas'][0][i]['page_id'],
                        "matched_text": results['documents'][0][i],
                        "collection": collection_name
                    })
            
            return output
            
        except Exception as e:
            print(f"✗ Ошибка при поиске: {e}")
            return []
    
    def delete_recipe(self, page_id: int) -> bool:
        """
        Удаление рецепта из векторной БД
        
        Args:
            page_id: ID страницы в БД
            
        Returns:
            True если успешно удалено
        """
        try:
            self.ingedients_collection.delete(ids=[str(page_id)])
            self.step_by_step_collection.delete(ids=[str(page_id)])
            self.description_collection.delete(ids=[str(page_id)])
            self.collection.delete(ids=[str(page_id)])
            print(f"✗ Удален рецепт ID: {page_id}")
            return True
        except Exception as e:
            print(f"✗ Ошибка при удалении рецепта {page_id}: {e}")
            return False
    
    def update_recipe(self, page: Page) -> bool:
        """
        Обновление рецепта (удаление + добавление)
        
        Args:
            page: Обновленный объект страницы
            
        Returns:
            True если успешно обновлено
        """
        self.delete_recipe(page.id)
        return self.add_recipe(page)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики коллекции
        
        Returns:
            Словарь со статистикой
        """
        main_count = self.collection.count()
        ingredients_count = self.ingedients_collection.count()
        instructions_count = self.step_by_step_collection.count()
        descriptions_count = self.description_collection.count()
        
        return {
            "total_recipes": main_count,
            "collections": {
                "main": main_count,
                "ingredients": ingredients_count,
                "instructions": instructions_count,
                "descriptions": descriptions_count
            },
            "collection_name": self.collection.name,
            "persist_directory": self.persist_directory,
        }
    
    def reset_collection(self, collection_name: str = "recipes"):
        """Очистка коллекции (удаление всех данных)"""
        try:
            self.client.delete_collection(name=collection_name)
            self.collection = self.client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            print("⚠ Коллекция очищена")
        except Exception as e:
            print(f"✗ Ошибка при очистке коллекции: {e}")



