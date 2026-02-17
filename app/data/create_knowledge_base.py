"""
Knowledge Base Generator
========================
تحويل ملف analyses_with_prices.xlsx إلى JSON Knowledge Base
للاستخدام في RAG (Retrieval-Augmented Generation) System

Author: Smart Coding Assistant
Date: 2026-02-05
"""

# Fix encoding for Windows console
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import json
import os
from datetime import datetime

print("="*70)
print("🧠 Knowledge Base Generator - Wareed Medical Tests")
print("="*70)
print()

# ============================================
# Step 1: Load Data
# ============================================
print("📂 Step 1: Loading analyses data...")
print("-"*70)

input_file = "analyses_with_prices.xlsx"
if not os.path.exists(input_file):
    print(f"❌ ERROR: File '{input_file}' not found!")
    exit(1)

df = pd.read_excel(input_file)
print(f"✅ Loaded {len(df)} analyses from '{input_file}'")
print(f"📊 Available columns: {df.columns.tolist()}")
print()

# ============================================
# Step 2: Column Mapping
# ============================================
print("🗺️  Step 2: Mapping columns...")
print("-"*70)

# Map Arabic column names to English field names for JSON
column_mapping = {
    'اسم التحليل بالعربية': 'analysis_name_ar',
    'Unnamed: 0': 'analysis_name_en',
    'english_name': 'analysis_name_en',
    'فائدة التحليل': 'description',
    'التحاليل المكملة': 'complementary_tests',
    'تحاليل قريبة': 'related_tests',
    'تحاليل بديلة': 'alternative_tests',
    'نوع العينة': 'sample_type',
    'تصنيف التحليل': 'category',
    'الأعراض': 'symptoms',
    'التحضير قبل التحليل': 'preparation',
    'price': 'price',
    'matched_name': 'service_name',
    'match_score': 'match_confidence'
}

# Select and rename columns
selected_cols = []
renamed_cols = {}

for ar_name, en_name in column_mapping.items():
    if ar_name in df.columns:
        selected_cols.append(ar_name)
        renamed_cols[ar_name] = en_name
        print(f"   ✅ '{ar_name}' → '{en_name}'")
    else:
        print(f"   ⚠️  Column '{ar_name}' not found")

print()

# ============================================
# Step 3: Data Cleaning
# ============================================
print("🧹 Step 3: Cleaning data...")
print("-"*70)

# Select and rename columns
df_clean = df[selected_cols].copy()
df_clean.rename(columns=renamed_cols, inplace=True)

# Replace NaN with None for JSON
df_clean = df_clean.where(pd.notna(df_clean), None)

# Convert float columns to proper types
if 'price' in df_clean.columns:
    df_clean['price'] = df_clean['price'].apply(lambda x: float(x) if x is not None else None)

if 'match_confidence' in df_clean.columns:
    df_clean['match_confidence'] = df_clean['match_confidence'].apply(lambda x: float(x) if x is not None else None)

print(f"✅ Cleaned {len(df_clean)} records")
print(f"📊 Final fields: {df_clean.columns.tolist()}")
print()

# ============================================
# Step 4: Convert to JSON
# ============================================
print("🔄 Step 4: Converting to JSON format...")
print("-"*70)

# Convert each row to dictionary
knowledge_base = df_clean.to_dict(orient='records')

# Add metadata
output_data = {
    "metadata": {
        "title": "Wareed Medical Laboratory - Tests Knowledge Base",
        "description": "Comprehensive database of medical laboratory tests with prices and descriptions",
        "version": "1.0.0",
        "created_at": datetime.now().isoformat(),
        "total_tests": len(knowledge_base),
        "source": "analyses_main.xlsx + analyses_prices.xls",
        "language": "ar",
        "secondary_language": "en"
    },
    "tests": knowledge_base
}

print(f"✅ Converted {len(knowledge_base)} tests to JSON format")
print()

# ============================================
# Step 5: Save JSON Files
# ============================================
print("💾 Step 5: Saving JSON files...")
print("-"*70)

# Save full knowledge base with metadata
output_file_full = "knowledge_base_full.json"
with open(output_file_full, 'w', encoding='utf-8') as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)
print(f"✅ Saved full knowledge base: {output_file_full}")
print(f"   📦 Size: {os.path.getsize(output_file_full) / 1024:.2f} KB")

# Save simplified version (tests only, no metadata)
output_file_simple = "knowledge_base.json"
with open(output_file_simple, 'w', encoding='utf-8') as f:
    json.dump(knowledge_base, f, ensure_ascii=False, indent=2)
print(f"✅ Saved simplified knowledge base: {output_file_simple}")
print(f"   📦 Size: {os.path.getsize(output_file_simple) / 1024:.2f} KB")

# Save compact version (no indentation)
output_file_compact = "knowledge_base_compact.json"
with open(output_file_compact, 'w', encoding='utf-8') as f:
    json.dump(knowledge_base, f, ensure_ascii=False)
print(f"✅ Saved compact knowledge base: {output_file_compact}")
print(f"   📦 Size: {os.path.getsize(output_file_compact) / 1024:.2f} KB")

print()

# ============================================
# Step 6: Generate Statistics
# ============================================
print("📊 Step 6: Knowledge Base Statistics...")
print("-"*70)

# Count tests with prices
tests_with_price = sum(1 for test in knowledge_base if test.get('price') is not None)
tests_without_price = len(knowledge_base) - tests_with_price

print(f"📋 Total tests: {len(knowledge_base)}")
print(f"💵 Tests with price: {tests_with_price} ({tests_with_price/len(knowledge_base)*100:.1f}%)")
print(f"❌ Tests without price: {tests_without_price} ({tests_without_price/len(knowledge_base)*100:.1f}%)")

if tests_with_price > 0:
    prices = [test['price'] for test in knowledge_base if test.get('price') is not None]
    print(f"\n💰 Price Statistics:")
    print(f"   Minimum: {min(prices):.2f} EGP")
    print(f"   Maximum: {max(prices):.2f} EGP")
    print(f"   Average: {sum(prices)/len(prices):.2f} EGP")

print()

# ============================================
# Step 7: Sample Output
# ============================================
print("📝 Step 7: Sample JSON output (first 2 tests)...")
print("-"*70)
print(json.dumps(knowledge_base[:2], ensure_ascii=False, indent=2))
print()

# ============================================
# Step 8: Save Summary
# ============================================
print("📄 Step 8: Saving generation summary...")
print("-"*70)

summary = f"""Knowledge Base Generation Summary
{'='*70}

Generation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Source File: {input_file}

Statistics:
-----------
Total Tests: {len(knowledge_base)}
Tests with Price: {tests_with_price} ({tests_with_price/len(knowledge_base)*100:.1f}%)
Tests without Price: {tests_without_price} ({tests_without_price/len(knowledge_base)*100:.1f}%)

Output Files:
-------------
1. {output_file_full} - Full version with metadata ({os.path.getsize(output_file_full) / 1024:.2f} KB)
2. {output_file_simple} - Simplified version ({os.path.getsize(output_file_simple) / 1024:.2f} KB)
3. {output_file_compact} - Compact version ({os.path.getsize(output_file_compact) / 1024:.2f} KB)

Fields Included:
----------------
{chr(10).join(f'- {field}' for field in df_clean.columns)}

Next Steps:
-----------
1. Use knowledge_base.json in your RAG system
2. Update app/data/knowledge_loader.py to load this file
3. Test the chatbot with the new knowledge base

{'='*70}
"""

summary_file = "knowledge_base_generation_summary.txt"
with open(summary_file, 'w', encoding='utf-8') as f:
    f.write(summary)

print(f"✅ Summary saved to: {summary_file}")
print()

print("="*70)
print("✨ Knowledge Base Generation Complete!")
print("="*70)
print()
print("📁 Generated Files:")
print(f"   1. {output_file_full}")
print(f"   2. {output_file_simple}")
print(f"   3. {output_file_compact}")
print(f"   4. {summary_file}")
print()
print("🎯 Next Steps:")
print("   1. Review the generated JSON files")
print("   2. Update your RAG system to use knowledge_base.json")
print("   3. Test the chatbot with sample queries")
print()
