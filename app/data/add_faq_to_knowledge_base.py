"""
FAQ Integration into Knowledge Base
=====================================
إضافة الأسئلة الشائعة إلى قاعدة المعرفة

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
print("📚 FAQ Integration - Adding FAQs to Knowledge Base")
print("="*70)
print()

# ============================================
# Step 1: Load FAQ File
# ============================================
print("📂 Step 1: Loading FAQ file...")
print("-"*70)

faq_file = "faq.xlsx"
if not os.path.exists(faq_file):
    print(f"❌ ERROR: File '{faq_file}' not found!")
    exit(1)

df_faq = pd.read_excel(faq_file)
print(f"✅ Loaded {len(df_faq)} FAQs from '{faq_file}'")
print(f"📊 Columns: {df_faq.columns.tolist()}")
print()

# ============================================
# Step 2: Process FAQ Data
# ============================================
print("🔄 Step 2: Processing FAQ data...")
print("-"*70)

# Rename columns to English
df_faq.columns = ['question', 'answer']

# Clean data
df_faq = df_faq.where(pd.notna(df_faq), None)

# Convert to dict
faqs = df_faq.to_dict(orient='records')

# Add metadata
for i, faq in enumerate(faqs):
    faq['id'] = f"faq_{i+1}"
    faq['type'] = 'faq'
    faq['category'] = 'general'

print(f"✅ Processed {len(faqs)} FAQs")
print()

# Display sample
print("📋 Sample FAQ:")
print(json.dumps(faqs[0], ensure_ascii=False, indent=2))
print()

# ============================================
# Step 3: Load Existing Knowledge Base
# ============================================
print("📂 Step 3: Loading existing knowledge base...")
print("-"*70)

kb_file = "knowledge_base.json"
if not os.path.exists(kb_file):
    print(f"❌ ERROR: Knowledge base '{kb_file}' not found!")
    print("   Please run create_knowledge_base.py first!")
    exit(1)

with open(kb_file, 'r', encoding='utf-8') as f:
    tests_kb = json.load(f)

print(f"✅ Loaded {len(tests_kb)} tests from knowledge base")
print()

# ============================================
# Step 4: Create Unified Knowledge Base
# ============================================
print("🔗 Step 4: Creating unified knowledge base...")
print("-"*70)

# Create unified structure
unified_kb = {
    "metadata": {
        "title": "Wareed Medical Laboratory - Complete Knowledge Base",
        "description": "Comprehensive database including medical tests and FAQs",
        "version": "2.0.0",
        "created_at": datetime.now().isoformat(),
        "total_tests": len(tests_kb),
        "total_faqs": len(faqs),
        "total_items": len(tests_kb) + len(faqs),
        "language": "ar",
        "secondary_language": "en"
    },
    "tests": tests_kb,
    "faqs": faqs
}

print(f"✅ Created unified knowledge base:")
print(f"   📊 Tests: {len(tests_kb)}")
print(f"   ❓ FAQs: {len(faqs)}")
print(f"   📦 Total items: {len(tests_kb) + len(faqs)}")
print()

# ============================================
# Step 5: Save Knowledge Base Files
# ============================================
print("💾 Step 5: Saving unified knowledge base...")
print("-"*70)

# Save full version with metadata
output_full = "knowledge_base_with_faq.json"
with open(output_full, 'w', encoding='utf-8') as f:
    json.dump(unified_kb, f, ensure_ascii=False, indent=2)
print(f"✅ Saved full version: {output_full}")
print(f"   📦 Size: {os.path.getsize(output_full) / 1024:.2f} KB")

# Save FAQs only
output_faq = "faq.json"
with open(output_faq, 'w', encoding='utf-8') as f:
    json.dump(faqs, f, ensure_ascii=False, indent=2)
print(f"✅ Saved FAQs only: {output_faq}")
print(f"   📦 Size: {os.path.getsize(output_faq) / 1024:.2f} KB")

# Save simplified version (all items in one array)
all_items = []

# Add tests with type marker
for test in tests_kb:
    test_with_type = test.copy()
    test_with_type['type'] = 'test'
    all_items.append(test_with_type)

# Add FAQs
all_items.extend(faqs)

output_simple = "knowledge_base_unified.json"
with open(output_simple, 'w', encoding='utf-8') as f:
    json.dump(all_items, f, ensure_ascii=False, indent=2)
print(f"✅ Saved unified array: {output_simple}")
print(f"   📦 Size: {os.path.getsize(output_simple) / 1024:.2f} KB")

print()

# ============================================
# Step 6: Generate Summary
# ============================================
print("📊 Step 6: Summary Statistics...")
print("-"*70)

print(f"\n📈 Knowledge Base Statistics:")
print(f"   📋 Medical Tests: {len(tests_kb)}")
print(f"   ❓ FAQs: {len(faqs)}")
print(f"   📦 Total Items: {len(all_items)}")
print()

print("📝 Sample FAQs:")
for i, faq in enumerate(faqs[:3], 1):
    q = faq['question'][:60] + "..." if len(faq['question']) > 60 else faq['question']
    print(f"   {i}. {q}")
print()

# ============================================
# Step 7: Save Summary
# ============================================
summary = f"""Knowledge Base with FAQ Integration Summary
{'='*70}

Generation Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Source Files: 
  - {kb_file} (Medical Tests)
  - {faq_file} (Frequently Asked Questions)

Statistics:
-----------
Medical Tests: {len(tests_kb)}
FAQs: {len(faqs)}
Total Items: {len(all_items)}

Output Files:
-------------
1. {output_full} - Full version with metadata ({os.path.getsize(output_full) / 1024:.2f} KB)
2. {output_faq} - FAQs only ({os.path.getsize(output_faq) / 1024:.2f} KB)
3. {output_simple} - Unified array format ({os.path.getsize(output_simple) / 1024:.2f} KB)

Structure:
----------
knowledge_base_with_faq.json:
{{
  "metadata": {{ ... }},
  "tests": [ ... {len(tests_kb)} tests ... ],
  "faqs": [ ... {len(faqs)} FAQs ... ]
}}

knowledge_base_unified.json:
[
  {{ "type": "test", ... }},  ← {len(tests_kb)} tests
  {{ "type": "faq", ... }}    ← {len(faqs)} FAQs
]

Next Steps:
-----------
1. Use knowledge_base_with_faq.json for structured access (tests & FAQs separate)
2. Use knowledge_base_unified.json for unified search (all items in one array)
3. Update your RAG system to handle both types: "test" and "faq"
4. Implement FAQ-specific responses for better UX

{'='*70}
"""

summary_file = "faq_integration_summary.txt"
with open(summary_file, 'w', encoding='utf-8') as f:
    f.write(summary)

print(f"✅ Summary saved to: {summary_file}")
print()

print("="*70)
print("✨ FAQ Integration Complete!")
print("="*70)
print()
print("📁 Generated Files:")
print(f"   1. {output_full} (with metadata)")
print(f"   2. {output_simple} (unified array)")
print(f"   3. {output_faq} (FAQs only)")
print(f"   4. {summary_file} (summary)")
print()
print("🎯 Recommended Usage:")
print("   Use knowledge_base_with_faq.json for your RAG system")
print("   Access tests via: data['tests']")
print("   Access FAQs via: data['faqs']")
print()
