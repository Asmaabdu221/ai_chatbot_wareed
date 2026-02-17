"""Test knowledge integration"""
import sys
sys.path.insert(0, '.')

from app.data.knowledge_integrator import integrated_knowledge

print("=" * 60)
print("Testing Knowledge Base Integration")
print("=" * 60)

# Print stats
stats = integrated_knowledge.get_stats()
print("\nStatistics:")
for key, value in stats.items():
    print(f"  {key}: {value}")

# Save unified knowledge
print("\nSaving unified knowledge base...")
if integrated_knowledge.save_unified_knowledge():
    print("Success!")
else:
    print("Failed!")

print("=" * 60)
