"""Test knowledge integrator"""
from app.data.knowledge_integrator import integrated_knowledge, get_knowledge_context

print("="*60)
print("Testing Knowledge Base Integration")
print("="*60)

# Print stats
print("\nTotal tests:", integrated_knowledge.metadata['total_tests'])
print("Sources:", integrated_knowledge.metadata['sources'])

# Test search for IGF-1
print("\n" + "="*60)
print("Searching for: عامل النمو")
print("="*60)
results = integrated_knowledge.search_tests("عامل النمو")
print(f"Found {len(results)} results:")
for test in results[:5]:
    print(f"  - {test.name_ar}")
    if test.benefits:
        print(f"    Benefits: {test.benefits[:100]}...")
    if test.price:
        print(f"    Price: {test.price}")

# Test get_knowledge_context
print("\n" + "="*60)
print("Testing get_knowledge_context with query")
print("="*60)
context = get_knowledge_context(user_query="عامل النمو الشبيه بالأنسولين")
print(f"Context length: {len(context)} chars")
print("\nFirst 1000 chars of context:")
print(context[:1000])

print("\n" + "="*60)
print("Done!")
print("="*60)
