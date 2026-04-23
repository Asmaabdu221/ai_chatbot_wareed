import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.data.rag_pipeline import get_grounded_context

ctx, has_match = get_grounded_context('السكري', max_tests=1)
with open('C:/Users/PC/.gemini/antigravity/brain/3e574ada-7a8c-48c4-b052-1c87cf53d453/scratch/context.txt', 'w', encoding='utf-8') as f:
    f.write(ctx)
print("WROTE CONTEXT")
