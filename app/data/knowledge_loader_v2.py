"""
Enhanced Knowledge Base Loader Module (Version 2.0)
====================================================
Handles loading and querying the medical knowledge base including:
- Medical tests with prices
- FAQs
- Fuzzy search capabilities

Author: Smart Coding Assistant
Date: 2026-02-05
"""

import json
import os
import re
import logging
from typing import Optional, Dict, Any, List, Tuple
try:
    from rapidfuzz import fuzz, process
except Exception:
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def partial_ratio(a: str, b: str) -> int:
            a = (a or "").lower()
            b = (b or "").lower()
            if not a or not b:
                return 0
            if a in b or b in a:
                return 95
            return int(SequenceMatcher(None, a, b).ratio() * 100)

    fuzz = _FuzzFallback()
    process = None

logger = logging.getLogger(__name__)


def _load_json_file(path: str) -> Optional[Dict]:
    """Load JSON file; allow NaN/Infinity for compatibility with exported data."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", path, e)
        return None

# Paths to knowledge base files
KNOWLEDGE_BASE_PATH = os.path.join(
    os.path.dirname(__file__),
    "knowledge_base_with_faq.json"
)

# Fallback to old knowledge base if new one doesn't exist
FALLBACK_KB_PATH = os.path.join(
    os.path.dirname(__file__),
    "knowledge.json"
)


class KnowledgeBaseV2:
    """
    Enhanced Knowledge Base manager for Wareed Medical Assistant
    Supports medical tests and FAQs with advanced search capabilities
    """
    
    def __init__(self):
        """Initialize and load the knowledge base"""
        self.data = None
        self.tests = []
        self.faqs = []
        self.metadata = {}
        self.load()
    
    def load(self) -> bool:
        """
        Load knowledge base from JSON file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if os.path.exists(KNOWLEDGE_BASE_PATH):
                self.data = _load_json_file(KNOWLEDGE_BASE_PATH)
                if not self.data:
                    return False
                self.metadata = self.data.get("metadata", {})
                self.tests = self.data.get("tests", [])
                self.faqs = self.data.get("faqs", [])
                logger.info("✅ Enhanced knowledge base loaded successfully")
                logger.info("   📊 Tests: %s, FAQs: %s", len(self.tests), len(self.faqs))
                return True

            if os.path.exists(FALLBACK_KB_PATH):
                self.data = _load_json_file(FALLBACK_KB_PATH)
                if not self.data:
                    return False
                self.tests = []
                self.faqs = []
                logger.warning("⚠️ Using fallback knowledge base (old format)")
                return True

            logger.error("❌ No knowledge base file found")
            return False
        except Exception as e:
            logger.error("❌ Error loading knowledge base: %s", e)
            self.data = {}
            return False
    
    # ============================================
    # Test Search Methods
    # ============================================
    
    def search_tests(
        self, 
        query: str, 
        search_in: List[str] = None,
        min_score: int = 60,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for tests using fuzzy matching
        
        Args:
            query: Search query (Arabic or English)
            search_in: Fields to search in (default: name, symptoms, description)
            min_score: Minimum similarity score (0-100)
            max_results: Maximum number of results
            
        Returns:
            List of matching tests with scores
        """
        if not self.tests:
            logger.warning("⚠️ No tests loaded in knowledge base")
            return []
        
        if search_in is None:
            search_in = [
                'analysis_name_ar',
                'analysis_name_en',
                'analysis_code',
                'synonyms',
                'related_tests',
                'alternative_tests',
                'symptoms',
                'description',
            ]
        
        results = []
        query_lower = query.strip().lower()
        query_words = set(query_lower.split())

        for test in self.tests:
            max_score = 0
            matched_field = None

            # Boost: if the query clearly contains the test name (e.g. "فيتامين د"), include it
            name_ar = (test.get("analysis_name_ar") or "").strip()
            name_en = (test.get("analysis_name_en") or "").strip()
            if name_ar:
                # Key part of name (before parenthesis, e.g. "فيتامين د" from "فيتامين د (25 هيدروكسي...)")
                key_ar = name_ar.split("(")[0].strip() if "(" in name_ar else name_ar
                if key_ar and len(key_ar) >= 2 and key_ar in query_lower:
                    max_score = max(max_score, 92)
                    matched_field = "analysis_name_ar"
            if name_en:
                key_en = name_en.split("(")[0].strip() if "(" in name_en else name_en
                if key_en and len(key_en) >= 2 and key_en.lower() in query_lower:
                    max_score = max(max_score, 92)
                    if not matched_field:
                        matched_field = "analysis_name_en"

            # Search in specified fields
            for field in search_in:
                field_value = test.get(field, '')
                if field_value and not isinstance(field_value, (int, float)):
                    score = fuzz.partial_ratio(query_lower, str(field_value).lower())
                    if score > max_score:
                        max_score = score
                        matched_field = field
                    # Also: if field value (or its key part) is contained IN the query, high score
                    fv = str(field_value).lower()
                    if field in ("analysis_name_ar", "analysis_name_en") and fv:
                        key = fv.split("(")[0].strip() if "(" in fv else fv
                        if len(key) >= 2 and key in query_lower:
                            max_score = max(max_score, 90)

            # Add to results if score is above threshold
            if max_score >= min_score:
                results.append({
                    'test': test,
                    'score': max_score,
                    'matched_field': matched_field
                })
        
        # Sort by score (highest first)
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results[:max_results]
    
    def get_test_by_name(self, name: str, exact: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get a specific test by name (Arabic or English)
        
        Args:
            name: Test name
            exact: If True, requires exact match; if False, uses fuzzy matching
            
        Returns:
            Test information or None if not found
        """
        if exact:
            # Exact match
            for test in self.tests:
                if (test.get('analysis_name_ar') == name or 
                    test.get('analysis_name_en') == name):
                    return test
            return None
        else:
            # Fuzzy match
            results = self.search_tests(name, max_results=1, min_score=80)
            return results[0]['test'] if results else None
    
    def get_tests_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Get all tests in a specific category
        
        Args:
            category: Category name (Arabic)
            
        Returns:
            List of tests in that category
        """
        return [test for test in self.tests if test.get('category') == category]
    
    def get_all_categories(self) -> List[str]:
        """Get list of all unique categories"""
        categories = set()
        for test in self.tests:
            cat = test.get('category')
            if cat:
                categories.add(cat)
        return sorted(list(categories))
    
    def get_tests_with_prices(self) -> List[Dict[str, Any]]:
        """Get all tests that have prices"""
        return [test for test in self.tests if test.get('price') is not None]
    
    def get_price_range(self) -> Tuple[float, float]:
        """
        Get price range (min, max)
        
        Returns:
            Tuple of (min_price, max_price)
        """
        prices = [test['price'] for test in self.tests if test.get('price') is not None]
        if prices:
            return (min(prices), max(prices))
        return (0.0, 0.0)
    
    # ============================================
    # FAQ Search Methods
    # ============================================
    
    def search_faqs(
        self, 
        query: str,
        min_score: int = 60,
        max_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search FAQs using fuzzy matching
        
        Args:
            query: Search query
            min_score: Minimum similarity score (0-100)
            max_results: Maximum number of results
            
        Returns:
            List of matching FAQs with scores
        """
        if not self.faqs:
            logger.warning("⚠️ No FAQs loaded in knowledge base")
            return []
        
        results = []
        query_lower = query.lower()
        
        for faq in self.faqs:
            # Search in question
            question_score = fuzz.partial_ratio(query_lower, faq.get('question', '').lower())
            # Search in answer
            answer_score = fuzz.partial_ratio(query_lower, faq.get('answer', '').lower())
            
            # Use the higher score
            max_score = max(question_score, answer_score)
            matched_in = 'question' if question_score > answer_score else 'answer'
            
            if max_score >= min_score:
                results.append({
                    'faq': faq,
                    'score': max_score,
                    'matched_in': matched_in
                })
        
        # Sort by score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results[:max_results]
    
    def get_all_faqs(self) -> List[Dict[str, Any]]:
        """Get all FAQs"""
        return self.faqs
    
    # ============================================
    # Unified Search Methods
    # ============================================
    
    def smart_search(
        self, 
        query: str,
        include_tests: bool = True,
        include_faqs: bool = True,
        max_results: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Smart search across both tests and FAQs
        
        Args:
            query: Search query
            include_tests: Include tests in search
            include_faqs: Include FAQs in search
            max_results: Maximum results per type
            
        Returns:
            Dictionary with 'tests' and 'faqs' keys containing results
        """
        results = {
            'tests': [],
            'faqs': [],
            'total_found': 0
        }
        
        if include_tests:
            test_results = self.search_tests(query, max_results=max_results)
            results['tests'] = test_results
            results['total_found'] += len(test_results)
        
        if include_faqs:
            faq_results = self.search_faqs(query, max_results=max_results)
            results['faqs'] = faq_results
            results['total_found'] += len(faq_results)
        
        return results
    
    # ============================================
    # Helper Methods
    # ============================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        tests_with_price = len(self.get_tests_with_prices())
        min_price, max_price = self.get_price_range()
        
        return {
            'total_tests': len(self.tests),
            'total_faqs': len(self.faqs),
            'total_items': len(self.tests) + len(self.faqs),
            'tests_with_price': tests_with_price,
            'tests_without_price': len(self.tests) - tests_with_price,
            'categories': len(self.get_all_categories()),
            'price_range': {
                'min': min_price,
                'max': max_price
            },
            'version': self.metadata.get('version', 'unknown')
        }
    
    def format_test_info(self, test: Dict[str, Any], include_price: bool = True) -> str:
        """
        Format test information for display
        
        Args:
            test: Test dictionary
            include_price: Include price in formatted text
            
        Returns:
            Formatted test information
        """
        lines = []
        
        # Test name
        name_ar = test.get('analysis_name_ar', 'غير متوفر')
        name_en = test.get('analysis_name_en', '')
        lines.append(f"🔬 **{name_ar}**")
        if name_en:
            lines.append(f"   ({name_en})")
        
        # Description
        desc = test.get('description')
        if desc:
            lines.append(f"\n📝 **الوصف:** {desc}")
        
        # Price
        if include_price:
            price = test.get('price')
            if price:
                lines.append(f"\n💰 **السعر:** {price} جنيه")
        
        # Sample type
        sample = test.get('sample_type')
        if sample:
            lines.append(f"\n🧪 **نوع العينة:** {sample}")
        
        # Category
        category = test.get('category')
        if category:
            lines.append(f"\n📂 **التصنيف:** {category}")
        
        # Symptoms
        symptoms = test.get('symptoms')
        if symptoms:
            lines.append(f"\n⚕️ **الأعراض:** {symptoms}")
        
        # Preparation
        prep = test.get('preparation')
        if prep:
            lines.append(f"\n📋 **التحضير:** {prep}")
        
        # Complementary tests
        comp = test.get('complementary_tests')
        if comp:
            lines.append(f"\n🔗 **تحاليل مكملة:** {comp}")
        
        return '\n'.join(lines)
    
    def format_faq_info(self, faq: Dict[str, Any]) -> str:
        """
        Format FAQ information for display
        
        Args:
            faq: FAQ dictionary
            
        Returns:
            Formatted FAQ information
        """
        question = faq.get('question', 'غير متوفر')
        answer = faq.get('answer', 'غير متوفر')
        
        return f"❓ **{question}**\n\n✅ {answer}"


# ============================================
# Global instance and helper functions
# ============================================

# Global knowledge base instance
_kb_instance = None


def get_kb_file_path() -> str:
    """Return path to the current KB file (primary or fallback)."""
    if os.path.exists(KNOWLEDGE_BASE_PATH):
        return KNOWLEDGE_BASE_PATH
    return FALLBACK_KB_PATH


def get_kb_file_mtime() -> Optional[float]:
    """Return last modification time of the current KB file, or None if missing."""
    path = get_kb_file_path()
    if not os.path.exists(path):
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def reload_knowledge_base() -> bool:
    """
    Reload knowledge base from disk and replace global instance.
    Clears context cache so new data is used. Call when KB file has changed.
    Returns True if reload succeeded.
    """
    global _kb_instance
    try:
        new_kb = KnowledgeBaseV2()
        if not new_kb.data:
            return False
        _kb_instance = new_kb
        try:
            from app.services.context_cache import get_context_cache
            get_context_cache().clear()
        except Exception as e:
            logger.debug("Context cache clear on reload: %s", e)
        try:
            from app.services.smart_cache import get_smart_cache
            get_smart_cache().preload_from_faqs(new_kb.faqs)
        except Exception as e:
            logger.debug("Smart cache preload on reload: %s", e)
        logger.info("🔄 Knowledge base reloaded successfully (auto-update)")
        return True
    except Exception as e:
        logger.exception("Failed to reload knowledge base: %s", e)
        return False


def get_knowledge_base() -> KnowledgeBaseV2:
    """Get or create global knowledge base instance"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBaseV2()
    return _kb_instance


def get_knowledge_context(
    user_message: str,
    max_tests: int = 3,
    max_faqs: int = 2,
    include_prices: bool = True
) -> str:
    """
    Get relevant knowledge context for a user message.
    Uses semantic search when embeddings cache is available, otherwise fuzzy search.
    Results are cached to avoid recomputing for the same (normalized) query.
    
    Args:
        user_message: User's message/question
        max_tests: Maximum number of tests to include
        max_faqs: Maximum number of FAQs to include
        include_prices: Include price information
        
    Returns:
        Formatted context string for AI
    """
    from app.services.context_cache import get_context_cache, make_context_cache_key

    key = make_context_cache_key(user_message, max_tests, max_faqs, include_prices)
    cache = get_context_cache()
    cached = cache.get(key)
    if cached is not None:
        logger.debug("Context cache HIT for knowledge context")
        return cached

    kb = get_knowledge_base()

    # Prefer semantic search when embeddings are available; fallback to fuzzy if no tests found
    try:
        from app.data.semantic_search import semantic_search, is_semantic_search_available
        if is_semantic_search_available():
            results = semantic_search(user_message, max_tests=max_tests, max_faqs=max_faqs)
            if not results.get("tests"):
                fuzzy_results = kb.smart_search(user_message, max_results=max(max_tests, max_faqs))
                results["tests"] = fuzzy_results.get("tests", [])
                if not results.get("faqs"):
                    results["faqs"] = fuzzy_results.get("faqs", [])
        else:
            results = kb.smart_search(user_message, max_results=max(max_tests, max_faqs))
    except Exception as e:
        logger.debug("Semantic search skipped, using fuzzy: %s", e)
        results = kb.smart_search(user_message, max_results=max(max_tests, max_faqs))
    
    # Record analysis usage for dashboard and chat insights
    try:
        from app.services.analysis_usage_tracker import get_analysis_usage_tracker
        tracker = get_analysis_usage_tracker()
        for result in results.get("tests") or []:
            t = result.get("test") or {}
            tracker.record(
                name_ar=t.get("analysis_name_ar") or "",
                name_en=t.get("analysis_name_en") or "",
            )
    except Exception as e:
        logger.debug("Analysis usage recording skipped: %s", e)

    context_parts = []
    
    # Add relevant tests
    if results['tests']:
        context_parts.append("📊 **معلومات التحاليل ذات الصلة:**\n")
        for i, result in enumerate(results['tests'][:max_tests], 1):
            test = result['test']
            formatted = kb.format_test_info(test, include_price=include_prices)
            context_parts.append(f"\n{i}. {formatted}\n")
            context_parts.append("-" * 50 + "\n")
    
    # Add relevant FAQs
    if results['faqs']:
        context_parts.append("\n\n❓ **أسئلة شائعة ذات صلة:**\n")
        for i, result in enumerate(results['faqs'][:max_faqs], 1):
            faq = result['faq']
            formatted = kb.format_faq_info(faq)
            context_parts.append(f"\n{i}. {formatted}\n")
            context_parts.append("-" * 50 + "\n")
    
    # If no results found
    if not results['tests'] and not results['faqs']:
        context_parts.append("⚠️ لم يتم العثور على معلومات محددة في قاعدة المعرفة.\n")
        context_parts.append("سأقدم إجابة عامة بناءً على معرفتي الطبية.\n")

    # If user seems to ask for usage stats, append top analyses for the model to use
    msg_lower = (user_message or "").strip().lower()
    if any(kw in msg_lower for kw in ("إحصائيات", "أكثر تحليل", "كم مرة", "التحاليل الأكثر", "استخدام التحاليل")):
        try:
            from app.services.analysis_usage_tracker import get_analysis_usage_tracker
            top5 = get_analysis_usage_tracker().get_top(5)
            if top5:
                lines = ["\n\n📈 **إحصائيات استخدام التحاليل (للاستجابة عند سؤال المستخدم):**"]
                for i, a in enumerate(top5, 1):
                    lines.append(f"  {i}. {a.get('name_ar', '—')} ({a.get('count', 0)} مرة)")
                context_parts.append("\n".join(lines))
        except Exception as e:
            logger.debug("Stats appendix skipped: %s", e)

    context_str = ''.join(context_parts)
    cache.set(key, context_str)
    return context_str


def search_by_symptom(symptom: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search for tests based on symptom
    
    Args:
        symptom: Symptom description
        max_results: Maximum number of results
        
    Returns:
        List of relevant tests
    """
    kb = get_knowledge_base()
    return kb.search_tests(
        symptom, 
        search_in=['symptoms'], 
        max_results=max_results
    )


def search_by_price_range(
    min_price: float, 
    max_price: float
) -> List[Dict[str, Any]]:
    """
    Get tests within a price range
    
    Args:
        min_price: Minimum price
        max_price: Maximum price
        
    Returns:
        List of tests in price range
    """
    kb = get_knowledge_base()
    return [
        test for test in kb.tests 
        if test.get('price') is not None and 
        min_price <= test.get('price') <= max_price
    ]


def get_test_statistics() -> Dict[str, Any]:
    """Get knowledge base statistics"""
    kb = get_knowledge_base()
    return kb.get_stats()


# ============================================
# Backward Compatibility
# ============================================

def load_knowledge_base() -> Dict[str, Any]:
    """
    Load knowledge base (backward compatible)
    
    Returns:
        Knowledge base data
    """
    kb = get_knowledge_base()
    return kb.data or {}
