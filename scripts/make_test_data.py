


import sys
from pathlib import Path
import sqlalchemy
import os
import shutil
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from src.common.database import DatabaseManager
from src.models import Page

def main():
    site_id = 1
    db = DatabaseManager()
    if not db.connect():
        print("Не удалось подключиться к базе данных")
        return
    ids = [15, 18]  # Пример списка ID страниц для экспорта, или None для всех
    session = db.get_session()
    sql = "SELECT * FROM pages WHERE site_id = :site_id and is_recipe = TRUE"
    if ids:
        ids_str = ','.join(map(str, ids))
        sql += f" AND id IN ({ids_str})"
    result = session.execute(sqlalchemy.text(sql), {"site_id": site_id})
    rows = result.fetchall()
    pages = [Page.model_validate(dict(row._mapping)) for row in rows]

    sql = "SELECT `name` FROM sites WHERE id = :id"
    result = session.execute(sqlalchemy.text(sql), {"id": site_id})
    site_name = result.scalar() or f"site_{site_id}"

    recipes_path = os.path.join("recipes", site_name)
    os.makedirs(recipes_path, exist_ok=True)

    for page in pages:
        if not page.html_path or not os.path.exists(page.html_path):
            print(f"HTML файл не найден для страницы {page.id}: {page.html_path}")
            continue
        
        # Получаем имя файла из html_path
        html_filename = os.path.basename(page.html_path)
        
        # Копируем HTML файл
        dest_html_path = os.path.join(recipes_path, html_filename)
        shutil.copy2(page.html_path, dest_html_path)


        # сохраняем файл с вытащенными данными из него
        extracted_data_path = html_filename.replace(".html", ".json")
        with open(os.path.join(recipes_path, extracted_data_path), "w", encoding="utf-8") as f:
            f.write(json.dumps(page.receipt_to_json(), ensure_ascii=False, indent=4))

    
    print(f"Всего скопировано {len(pages)} рецептов в {recipes_path}")
    session.close()





if __name__ == "__main__":
    main()