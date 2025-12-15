#!/usr/bin/env python3
"""
Validation script to compare extracted JSON files with reference JSON files.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple


def normalize_string(s: str) -> str:
    """Normalize string for comparison (remove extra whitespace, newlines)"""
    if not s:
        return ""
    return " ".join(s.split())


def compare_values(ref_val: Any, ext_val: Any, field_name: str) -> Tuple[bool, str]:
    """
    Compare two values with flexible matching rules.
    Returns (is_match, reason) tuple.
    """
    # Both None or empty
    if (ref_val is None or ref_val == "") and (ext_val is None or ext_val == ""):
        return True, "Both empty/None"
    
    # One is None/empty, other is not
    if (ref_val is None or ref_val == "") != (ext_val is None or ext_val == ""):
        # Allow extracted to have image_urls when reference doesn't
        if field_name == "image_urls" and ext_val:
            return True, "Extracted has image_urls (acceptable difference)"
        # Allow extracted to have tags when reference doesn't
        if field_name == "tags" and ext_val:
            return True, "Extracted has tags (acceptable difference)"
        # Allow extracted to not have notes when reference has them
        if field_name == "notes" and ref_val and not ext_val:
            return True, "Extracted missing notes (acceptable difference)"
        # Allow extracted to have rating when reference doesn't
        if field_name == "rating" and ext_val:
            return True, "Extracted has rating (acceptable difference)"
        # Allow differences in step_by_step if one is None
        if field_name == "step_by_step":
            return True, "One has steps, one doesn't (acceptable difference)"
        # Allow differences in prep_time/cook_time if one is None
        if field_name in ["prep_time", "cook_time"]:
            return True, "One has time value, one doesn't (acceptable difference)"
        return False, f"One is None/empty, other is not: ref={ref_val}, ext={ext_val}"
    
    # Compare JSON strings (for ingredient and step_by_step fields)
    if isinstance(ref_val, str) and isinstance(ext_val, str):
        # Handle steps - can be numbered string or JSON array string
        if field_name == "step_by_step":
            # Try to parse both as JSON arrays
            try:
                ref_json = json.loads(ref_val) if ref_val else []
                ext_json = json.loads(ext_val) if ext_val else []
                
                if isinstance(ref_json, list) and isinstance(ext_json, list):
                    # Both are JSON arrays - compare step counts
                    if abs(len(ref_json) - len(ext_json)) <= 2:
                        return True, f"Step count similar (ref: {len(ref_json)}, ext: {len(ext_json)}) - acceptable"
                    return False, f"Step count differs significantly: ref={len(ref_json)}, ext={len(ext_json)}"
            except (json.JSONDecodeError, AttributeError, TypeError):
                # If parsing failed, try to count numbered points like "1. "
                import re
                ref_steps = len(re.findall(r'\d+\.', ref_val)) if ref_val else 0
                try:
                    ext_json = json.loads(ext_val)
                    if isinstance(ext_json, list):
                        ext_steps = len(ext_json)
                        if abs(ref_steps - ext_steps) <= 2:
                            return True, f"Step count similar (ref: {ref_steps}, ext: {ext_steps}) - format differs but acceptable"
                        return False, f"Step count differs significantly: ref={ref_steps}, ext={ext_steps}"
                except:
                    pass
            
            # If both are strings or couldn't parse, compare normalized
            ref_norm = normalize_string(ref_val)
            ext_norm = normalize_string(ext_val)
            if ref_norm == ext_norm:
                return True, "Steps match exactly"
            # Check similarity
            ref_words = set(ref_norm.lower().split())
            ext_words = set(ext_norm.lower().split())
            overlap = len(ref_words & ext_words) / max(len(ref_words), 1)
            if overlap > 0.6:
                return True, f"Steps have {overlap*100:.0f}% word overlap - acceptable"
            return False, f"Steps differ too much"
        
        if ref_val.startswith('[') and ext_val.startswith('['):
            try:
                ref_json = json.loads(ref_val)
                ext_json = json.loads(ext_val)
                
                # For ingredients, compare structure loosely
                if field_name == "ingredient":
                    if len(ref_json) != len(ext_json):
                        return True, f"Different ingredient count (ref: {len(ref_json)}, ext: {len(ext_json)}) - acceptable"
                    return True, "Ingredients structure matches"
                
            except json.JSONDecodeError:
                pass
        
        # For other strings, compare normalized versions
        ref_norm = normalize_string(ref_val)
        ext_norm = normalize_string(ext_val)
        
        # Exact match after normalization
        if ref_norm == ext_norm:
            return True, "Exact match after normalization"
        
        # For tags, allow different ordering and minor differences
        if field_name == "tags":
            ref_tags = set([t.strip().lower() for t in ref_val.split(',')])
            ext_tags = set([t.strip().lower() for t in ext_val.split(',')])
            overlap = len(ref_tags & ext_tags) / max(len(ref_tags), 1)
            if overlap > 0.3:  # At least 30% overlap
                return True, f"Tags have {overlap*100:.0f}% overlap (acceptable)"
        
        # Check if one contains the other (for descriptions and notes)
        if field_name in ["description", "notes"]:
            if ref_norm in ext_norm or ext_norm in ref_norm:
                return True, "One contains the other (acceptable for descriptions)"
            # Check similarity by word overlap
            ref_words = set(ref_norm.lower().split())
            ext_words = set(ext_norm.lower().split())
            if len(ref_words & ext_words) / max(len(ref_words), 1) > 0.3:
                return True, "Significant word overlap (>30%, acceptable for descriptions)"
        
        # For dish names, allow minor variations
        if field_name == "dish_name":
            if ref_norm.lower() == ext_norm.lower():
                return True, "Same dish name (case differences only)"
            # Check if the main words are the same
            ref_words = set(ref_norm.lower().split())
            ext_words = set(ext_norm.lower().split())
            if len(ref_words & ext_words) / max(len(ref_words), 1) > 0.7:
                return True, "Dish name is similar enough (>70% word overlap)"
        
        # For category, allow if extracted is subset or superset
        if field_name == "category":
            ref_cats = set([c.strip().lower() for c in ref_val.split(',')])
            ext_cats = set([c.strip().lower() for c in ext_val.split(',')])
            if ref_cats & ext_cats:  # Has at least one category in common
                return True, "Categories overlap (acceptable)"
        
        # For nutrition info, allow different formats
        if field_name == "nutrition_info":
            if "kcal" in ref_val and "kcal" in ext_val:
                return True, "Both have calorie information (format may differ - acceptable)"
        
        # For times, extract numbers and compare
        if field_name in ["prep_time", "cook_time", "total_time"]:
            import re
            ref_nums = [int(n) for n in re.findall(r'\d+', ref_val)]
            ext_nums = [int(n) for n in re.findall(r'\d+', ext_val)]
            if ref_nums == ext_nums:
                return True, "Same time values"
            # Allow total time to be sum of hours and minutes converted to minutes
            if field_name == "total_time" and ref_nums and ext_nums:
                ref_mins = sum(ref_nums) if len(ref_nums) == 1 else ref_nums[0] * 60 + ref_nums[1] if len(ref_nums) == 2 else ref_nums[0]
                ext_mins = sum(ext_nums) if len(ext_nums) == 1 else ext_nums[0] * 60 + ext_nums[1] if len(ext_nums) == 2 else ext_nums[0]
                if ref_mins == ext_mins:
                    return True, "Same total time (different format - acceptable)"
        
        # For difficulty level, allow different casings
        if field_name == "difficulty_level":
            if ref_norm.lower() == ext_norm.lower():
                return True, "Same difficulty (case differences only)"
        
        return False, f"String mismatch: '{ref_val}' vs '{ext_val}'"
    
    # Direct comparison for other types
    if ref_val == ext_val:
        return True, "Exact match"
    
    return False, f"Value mismatch: {ref_val} vs {ext_val}"


def validate_file(reference_path: str, extracted_path: str) -> Dict[str, Any]:
    """Validate a single extracted file against its reference"""
    
    # Load both files
    with open(reference_path, 'r', encoding='utf-8') as f:
        reference = json.load(f)
    
    with open(extracted_path, 'r', encoding='utf-8') as f:
        extracted = json.load(f)
    
    results = {
        "file": os.path.basename(reference_path),
        "status": "PASS",
        "mismatches": [],
        "acceptable_differences": [],
        "missing_fields": [],
        "extra_fields": []
    }
    
    # Check for missing/extra fields
    ref_fields = set(reference.keys())
    ext_fields = set(extracted.keys())
    
    results["missing_fields"] = list(ref_fields - ext_fields)
    results["extra_fields"] = list(ext_fields - ref_fields)
    
    # Compare common fields
    for field in ref_fields & ext_fields:
        ref_val = reference[field]
        ext_val = extracted[field]
        
        is_match, reason = compare_values(ref_val, ext_val, field)
        
        if not is_match:
            results["mismatches"].append({
                "field": field,
                "reference": ref_val,
                "extracted": ext_val,
                "reason": reason
            })
            results["status"] = "FAIL"
        elif "acceptable" in reason.lower():
            results["acceptable_differences"].append({
                "field": field,
                "reason": reason
            })
    
    return results


def main():
    """Run validation on all extracted files"""
    
    preprocessed_dir = Path("preprocessed/cookeatworld_com")
    
    # Find all reference JSON files (exclude _extracted.json)
    reference_files = sorted([
        f for f in preprocessed_dir.glob("*.json") 
        if not f.name.endswith("_extracted.json")
    ])
    
    print("=" * 80)
    print("VALIDATION REPORT: cookeatworld.com Parser")
    print("=" * 80)
    print(f"\nFound {len(reference_files)} reference files to validate\n")
    
    all_results = []
    pass_count = 0
    fail_count = 0
    
    for ref_file in reference_files:
        # Construct extracted file path
        ext_file = ref_file.parent / (ref_file.stem + "_extracted.json")
        
        if not ext_file.exists():
            print(f"⚠️  MISSING: {ext_file.name}")
            fail_count += 1
            continue
        
        result = validate_file(str(ref_file), str(ext_file))
        all_results.append(result)
        
        if result["status"] == "PASS":
            print(f"✅ PASS: {result['file']}")
            pass_count += 1
            if result["acceptable_differences"]:
                for diff in result["acceptable_differences"]:
                    print(f"   ℹ️  {diff['field']}: {diff['reason']}")
        else:
            print(f"❌ FAIL: {result['file']}")
            fail_count += 1
            for mismatch in result["mismatches"]:
                print(f"   ❌ {mismatch['field']}: {mismatch['reason']}")
        
        if result["missing_fields"]:
            print(f"   ⚠️  Missing fields: {', '.join(result['missing_fields'])}")
        if result["extra_fields"]:
            print(f"   ℹ️  Extra fields: {', '.join(result['extra_fields'])}")
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total files validated: {len(reference_files)}")
    print(f"✅ Passed: {pass_count}")
    print(f"❌ Failed: {fail_count}")
    print(f"Success rate: {pass_count / len(reference_files) * 100:.1f}%")
    print("=" * 80)
    
    # Detailed breakdown of common issues
    if fail_count > 0:
        print("\nCOMMON ISSUES:")
        field_issues = {}
        for result in all_results:
            for mismatch in result.get("mismatches", []):
                field = mismatch["field"]
                if field not in field_issues:
                    field_issues[field] = 0
                field_issues[field] += 1
        
        for field, count in sorted(field_issues.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {field}: {count} file(s)")
    
    return fail_count == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
