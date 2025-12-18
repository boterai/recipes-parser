import json
import re
from typing import Optional, List, Dict, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ChefkochDeExtractor(BaseRecipeExtractor):
    """Extractor for chefkoch.de recipe pages"""
    
    def __init__(self, html_path: str):
        super().__init__(html_path)
        self.nuxt_data = None
        self.recipe_data = self._extract_nuxt_data()
    
    def _resolve_value(self, value: Any) -> Any:
        """Resolve a value - if it's an int, look it up in nuxt_data array"""
        if not self.nuxt_data:
            return value
        
        # If it's an integer and points to a valid index, resolve it
        if isinstance(value, int) and 0 <= value < len(self.nuxt_data):
            return self.nuxt_data[value]
        
        return value
    
    def _extract_nuxt_data(self) -> Optional[Dict[str, Any]]:
        """Extract recipe data from __NUXT_DATA__ JSON"""
        script_tag = self.soup.find('script', {'id': '__NUXT_DATA__'})
        if not script_tag:
            return None
        
        try:
            # Parse the JSON-like array structure
            self.nuxt_data = json.loads(script_tag.string)
            
            # The structure is a complex nested array
            # Recipe data starts at index 4 in the main structure
            if not self.nuxt_data or len(self.nuxt_data) < 5:
                return None
            
            recipe_obj = self.nuxt_data[4]
            return recipe_obj
        except (json.JSONDecodeError, IndexError, KeyError):
            return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name/title"""
        if self.recipe_data:
            try:
                title_idx = self.recipe_data.get('title')
                title = self._resolve_value(title_idx)
                if title and isinstance(title, str):
                    return self.clean_text(title)
            except Exception:
                pass
        
        # Fallback to meta tags
        meta_title = self.soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
            # Remove " von [username]" suffix
            title = re.sub(r'\s+von\s+\w+$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        if self.recipe_data:
            try:
                subtitle_idx = self.recipe_data.get('subtitle')
                subtitle = self._resolve_value(subtitle_idx)
                if subtitle and isinstance(subtitle, str):
                    return self.clean_text(subtitle)
            except Exception:
                pass
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as JSON array"""
        if not self.recipe_data:
            return None
        
        try:
            groups_idx = self.recipe_data.get('ingredientGroups')
            ingredient_groups = self._resolve_value(groups_idx)
            
            if not ingredient_groups:
                return None
            
            all_ingredients = []
            
            for group_idx in ingredient_groups:
                group = self._resolve_value(group_idx)
                if not isinstance(group, dict):
                    continue
                
                ingredients_idx = group.get('ingredients')
                ingredients_list = self._resolve_value(ingredients_idx)
                
                if not ingredients_list:
                    continue
                
                for ing_idx in ingredients_list:
                    ing = self._resolve_value(ing_idx)
                    if not isinstance(ing, dict):
                        continue
                    
                    name_idx = ing.get('name')
                    name = self._resolve_value(name_idx)
                    
                    amount_idx = ing.get('amount')
                    amount = self._resolve_value(amount_idx)
                    
                    unit_idx = ing.get('unit')
                    unit = self._resolve_value(unit_idx)
                    
                    ingredient_obj = {
                        'name': name if isinstance(name, str) else '',
                        'amount': amount,
                        'units': unit if isinstance(unit, str) else None
                    }
                    all_ingredients.append(ingredient_obj)
            
            if all_ingredients:
                return json.dumps(all_ingredients, ensure_ascii=False)
        except Exception:
            pass
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract cooking steps as JSON array"""
        if not self.recipe_data:
            return None
        
        try:
            instructions_idx = self.recipe_data.get('instructions')
            instructions = self._resolve_value(instructions_idx)
            
            if instructions and isinstance(instructions, str):
                # Split by newlines and filter empty lines
                steps = [self.clean_text(step) for step in instructions.split('\n') if step.strip()]
                if steps:
                    return json.dumps(steps, ensure_ascii=False)
        except Exception:
            pass
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Extract nutrition information"""
        if not self.recipe_data:
            return None
        
        try:
            nutrition_idx = self.recipe_data.get('nutrition')
            nutrition = self._resolve_value(nutrition_idx)
            
            if nutrition and isinstance(nutrition, dict):
                kcal_idx = nutrition.get('kCalories')
                kcal = self._resolve_value(kcal_idx)
                
                protein_idx = nutrition.get('proteinContent')
                protein = self._resolve_value(protein_idx)
                
                fat_idx = nutrition.get('fatContent')
                fat = self._resolve_value(fat_idx)
                
                carbs_idx = nutrition.get('carbohydrateContent')
                carbs = self._resolve_value(carbs_idx)
                
                if kcal or protein or fat or carbs:
                    parts = []
                    if kcal:
                        parts.append(f"{kcal} kcal pro Portion")
                    if protein:
                        parts.append(f"{protein} g Eiweiß")
                    if fat:
                        parts.append(f"{fat} g Fett")
                    if carbs:
                        parts.append(f"{carbs} g Kohlenhydrate")
                    
                    return ", ".join(parts)
        except Exception:
            pass
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Extract recipe category"""
        if not self.recipe_data:
            return None
        
        try:
            tags_idx = self.recipe_data.get('tags')
            tags = self._resolve_value(tags_idx)
            
            if tags and isinstance(tags, list) and len(tags) > 0:
                first_tag_idx = tags[0]
                first_tag = self._resolve_value(first_tag_idx)
                if isinstance(first_tag, str):
                    return self.clean_text(first_tag)
        except Exception:
            pass
        
        return None
    
    def _convert_time(self, minutes: Optional[int]) -> Optional[str]:
        """Convert minutes to readable format"""
        if not minutes:
            return None
        
        if minutes < 60:
            return f"{minutes} minutes"
        else:
            hours = minutes // 60
            mins = minutes % 60
            if mins == 0:
                return f"{hours} hour{'s' if hours > 1 else ''}"
            else:
                return f"{hours} hour{'s' if hours > 1 else ''} {mins} minutes"
    
    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time"""
        if not self.recipe_data:
            return None
        
        try:
            prep_time_idx = self.recipe_data.get('preparationTime')
            prep_time = self._resolve_value(prep_time_idx)
            if isinstance(prep_time, int):
                return self._convert_time(prep_time)
        except Exception:
            pass
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time"""
        if not self.recipe_data:
            return None
        
        try:
            cook_time_idx = self.recipe_data.get('cookingTime')
            cook_time = self._resolve_value(cook_time_idx)
            if isinstance(cook_time, int):
                return self._convert_time(cook_time)
        except Exception:
            pass
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Extract total time"""
        if not self.recipe_data:
            return None
        
        try:
            total_time_idx = self.recipe_data.get('totalTime')
            total_time = self._resolve_value(total_time_idx)
            if isinstance(total_time, int):
                return self._convert_time(total_time)
        except Exception:
            pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Extract additional notes"""
        if not self.recipe_data:
            return None
        
        try:
            notes_idx = self.recipe_data.get('miscellaneousText')
            notes = self._resolve_value(notes_idx)
            if notes and isinstance(notes, str):
                return self.clean_text(notes)
        except Exception:
            pass
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        if not self.recipe_data:
            return None
        
        try:
            image_id_idx = self.recipe_data.get('previewImageId')
            preview_image_id = self._resolve_value(image_id_idx)
            
            recipe_id_idx = self.recipe_data.get('id')
            recipe_id = self._resolve_value(recipe_id_idx)
            
            if preview_image_id and recipe_id:
                # Build image URL based on chefkoch.de pattern
                base_url = f"https://img.chefkoch-cdn.de/rezepte/{recipe_id}/bilder/{preview_image_id}"
                return f"{base_url}/crop-960x720/"
        except Exception:
            pass
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract tags"""
        if not self.recipe_data:
            return None
        
        try:
            tags_idx = self.recipe_data.get('tags')
            tags = self._resolve_value(tags_idx)
            
            if tags and isinstance(tags, list):
                tag_strings = []
                for tag_idx in tags:
                    tag = self._resolve_value(tag_idx)
                    if isinstance(tag, str):
                        tag_strings.append(self.clean_text(tag))
                
                if tag_strings:
                    return ", ".join(tag_strings)
        except Exception:
            pass
        
        return None
    
    def extract_all(self) -> Dict[str, Any]:
        """Extract all recipe data"""
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }

def main():
    from pathlib import Path
    """Обработка рецептов из директории recipes/chefkoch_de"""
    # По умолчанию обрабатываем папку recipes/kikkoman_co_jp
    recipes_dir = "recipes/chefkoch_de"
    if Path(recipes_dir).exists() and Path(recipes_dir).is_dir():
        process_directory(ChefkochDeExtractor, recipes_dir)
    else:
        print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":

    main()