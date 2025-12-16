#!/usr/bin/env python
"""
Script to test and verify the receiteria.com.br parser
"""

import json
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from extractor.receiteria_com_br import ReceiteriaCombBrExtractor


def test_parser():
    """Test the receiteria parser with sample files"""
    test_dir = Path("preprocessed/receiteria_com_br")
    
    if not test_dir.exists():
        print(f"❌ Test directory not found: {test_dir}")
        return False
    
    html_files = list(test_dir.glob("*.html"))
    
    if not html_files:
        print(f"❌ No HTML files found in {test_dir}")
        return False
    
    print(f"Found {len(html_files)} HTML files to test")
    print("=" * 80)
    
    all_passed = True
    
    for html_file in html_files:
        print(f"\nTesting: {html_file.name}")
        print("-" * 80)
        
        try:
            # Parse the HTML
            extractor = ReceiteriaCombBrExtractor(str(html_file))
            result = extractor.extract_all()
            
            # Check that all required fields are present
            required_fields = [
                'dish_name', 'description', 'ingredient', 'step_by_step',
                'nutrition_info', 'category', 'prep_time', 'cook_time',
                'total_time', 'servings', 'difficulty_level', 'rating', 'notes', 
                'tags', 'image_urls'
            ]
            
            missing_fields = [field for field in required_fields if field not in result]
            
            if missing_fields:
                print(f"❌ Missing fields: {', '.join(missing_fields)}")
                all_passed = False
            else:
                print("✓ All required fields present")
            
            # Display extracted data
            print("\nExtracted data:")
            for field in required_fields:
                value = result.get(field)
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                print(f"  {field}: {value}")
            
            # Check if reference JSON exists
            ref_json = html_file.with_suffix('.json')
            if ref_json.exists():
                with open(ref_json, 'r', encoding='utf-8') as f:
                    reference = json.load(f)
                
                # Compare key fields
                print("\nComparison with reference:")
                
                # Compare dish_name
                if result.get('dish_name') == reference.get('dish_name'):
                    print("  ✓ dish_name matches")
                else:
                    print(f"  ⚠ dish_name differs:")
                    print(f"    Got: {result.get('dish_name')}")
                    print(f"    Expected: {reference.get('dish_name')}")
                
                # Compare category
                if result.get('category') == reference.get('category'):
                    print("  ✓ category matches")
                else:
                    print(f"  ⚠ category differs:")
                    print(f"    Got: {result.get('category')}")
                    print(f"    Expected: {reference.get('category')}")
                
                # Compare times
                for time_field in ['prep_time', 'cook_time', 'total_time']:
                    if result.get(time_field) == reference.get(time_field):
                        print(f"  ✓ {time_field} matches")
                    else:
                        print(f"  ⚠ {time_field} differs:")
                        print(f"    Got: {result.get(time_field)}")
                        print(f"    Expected: {reference.get(time_field)}")
            
            print("✓ Parsing successful")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✓ All tests passed!")
        return True
    else:
        print("❌ Some tests failed")
        return False


if __name__ == "__main__":
    success = test_parser()
    sys.exit(0 if success else 1)
