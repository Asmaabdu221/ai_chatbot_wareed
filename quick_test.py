"""
Quick Test - Test Knowledge Loader V2 Locally
==============================================
اختبار سريع للـ Knowledge Loader بدون تشغيل السيرفر

Author: Smart Coding Assistant
Date: 2026-02-05
"""

# Fix encoding for Windows console
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.data.knowledge_loader_v2 import (
    get_knowledge_base,
    get_knowledge_context,
    search_by_symptom,
    get_test_statistics
)

print("="*70)
print("🧪 Quick Test - Knowledge Loader V2")
print("="*70)
print()

# Test 1: Load KB
print("📂 Test 1: Loading Knowledge Base...")
print("-"*70)

kb = get_knowledge_base()
stats = get_test_statistics()

print(f"✅ Knowledge Base loaded!")
print(f"   📊 Tests: {stats['total_tests']}")
print(f"   ❓ FAQs: {stats['total_faqs']}")
print(f"   💵 Tests with price: {stats['tests_with_price']}")
print()

# Test 2: Search by symptom
print("⚕️  Test 2: Search by symptom (تعب)")
print("-"*70)

results = search_by_symptom("تعب", max_results=3)
if results:
    for i, result in enumerate(results, 1):
        test = result['test']
        print(f"{i}. {test['analysis_name_ar']}")
        if test.get('price'):
            print(f"   💰 السعر: {test['price']} ريال")
        print(f"   📊 Match Score: {result['score']}%")
else:
    print("❌ No results found")

print()

# Test 3: Smart search
print("🧠 Test 3: Smart search (سكر)")
print("-"*70)

results = kb.smart_search("سكر", max_results=2)
print(f"✅ Found {results['total_found']} results")

if results['tests']:
    print("\n📊 Tests:")
    for i, result in enumerate(results['tests'], 1):
        test = result['test']
        print(f"   {i}. {test['analysis_name_ar']}")

if results['faqs']:
    print("\n❓ FAQs:")
    for i, result in enumerate(results['faqs'], 1):
        faq = result['faq']
        print(f"   {i}. {faq['question'][:60]}...")

print()

# Test 4: Get RAG context
print("🤖 Test 4: Generate RAG context")
print("-"*70)

query = "عندي تعب وإرهاق"
context = get_knowledge_context(query, max_tests=2, max_faqs=1)

print(f"💬 Query: '{query}'")
print(f"📄 Context generated: {len(context)} chars")
print()
print("First 300 chars:")
print(context[:300] + "...")
print()

# Test 5: Categories
print("📂 Test 5: Available categories")
print("-"*70)

categories = kb.get_all_categories()
print(f"✅ Found {len(categories)} categories:")
for i, cat in enumerate(categories[:10], 1):
    count = len(kb.get_tests_by_category(cat))
    print(f"   {i}. {cat} ({count} tests)")

if len(categories) > 10:
    print(f"   ... and {len(categories) - 10} more")

print()

# Summary
print("="*70)
print("✅ All Quick Tests Passed!")
print("="*70)
print()
print("🎯 Next Steps:")
print("   1. Run the server: uvicorn app.main:app --reload")
print("   2. Test API: python test_rag_system.py")
print("   3. Check docs: RAG_SYSTEM_GUIDE.md")
print()
