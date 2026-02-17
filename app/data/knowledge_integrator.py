"""
Knowledge Base Integrator
Merges Excel data with existing knowledge.json into a unified knowledge base
"""

import json
import os
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Paths
KNOWLEDGE_JSON_PATH = os.path.join(os.path.dirname(__file__), "knowledge.json")
EXCEL_JSON_PATH = os.path.join(os.path.dirname(__file__), "excel_data.json")
UNIFIED_JSON_PATH = os.path.join(os.path.dirname(__file__), "unified_knowledge.json")


@dataclass
class TestInfo:
    """Unified test information schema"""
    id: str
    name_ar: str
    name_en: Optional[str] = None
    price: Optional[str] = None
    category: Optional[str] = None
    benefits: Optional[str] = None
    preparation: Optional[str] = None
    symptoms: Optional[List[str]] = None
    related_tests: Optional[List[str]] = None
    alternative_tests: Optional[List[str]] = None
    sample_type: Optional[str] = None
    complementary_tests: Optional[str] = None
    source: str = "manual"  # "manual", "excel", "merged"
    
    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


class IntegratedKnowledgeBase:
    """
    Integrated Knowledge Base that combines:
    1. Existing knowledge.json (company info, services, manual tests)
    2. Excel data (574 tests with detailed information)
    """
    
    def __init__(self):
        self.company_info = {}
        self.services = []
        self.tests = {}  # Dict[test_id, TestInfo]
        self.tests_by_name = {}  # Dict[name_ar, TestInfo] for quick lookup
        self.tests_by_category = {}  # Dict[category, List[TestInfo]]
        self.metadata = {
            "version": "2.0",
            "total_tests": 0,
            "sources": {
                "knowledge_json": 0,
                "excel": 0,
                "merged": 0
            }
        }
        
        self.load_all()
    
    def load_all(self):
        """Load and merge all knowledge sources"""
        logger.info("Loading integrated knowledge base...")
        
        # Load company info and services from knowledge.json
        self._load_company_info()
        
        # Load tests from knowledge.json
        self._load_knowledge_json_tests()
        
        # Load tests from Excel
        self._load_excel_tests()
        
        # Build indexes
        self._build_indexes()
        
        # Update metadata
        self.metadata["total_tests"] = len(self.tests)
        
        logger.info(f"✅ Loaded {self.metadata['total_tests']} tests:")
        logger.info(f"   - knowledge.json: {self.metadata['sources']['knowledge_json']}")
        logger.info(f"   - Excel: {self.metadata['sources']['excel']}")
        logger.info(f"   - Merged: {self.metadata['sources']['merged']}")
    
    def _load_company_info(self):
        """Load company info and services from knowledge.json"""
        try:
            with open(KNOWLEDGE_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.company_info = {
                "name": data.get("الشركة", {}).get("الاسم"),
                "description": data.get("الشركة", {}).get("الوصف"),
                "branches": data.get("الشركة", {}).get("عدد_الفروع"),
                "mission": data.get("الرسالة"),
                "vision": data.get("الرؤية"),
                "contact": data.get("معلومات_الاتصال", {}),
                "features": data.get("المميزات", []),
                "values": data.get("القيم_الأساسية", [])
            }
            
            self.services = data.get("الخدمات", [])
            
            logger.info(f"✅ Loaded company info and {len(self.services)} services")
        
        except Exception as e:
            logger.error(f"❌ Error loading company info: {e}")
    
    def _load_knowledge_json_tests(self):
        """Load tests from knowledge.json"""
        try:
            with open(KNOWLEDGE_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load individual tests
            individual_tests = data.get("الباقات_والتحاليل", {}).get("التحاليل_الفردية", {}).get("التحاليل", [])
            
            for test in individual_tests:
                test_id = f"kg_{len(self.tests) + 1:04d}"
                test_info = TestInfo(
                    id=test_id,
                    name_ar=test.get("الاسم", ""),
                    price=test.get("السعر", ""),
                    category=test.get("التصنيف", ""),
                    source="knowledge.json"
                )
                self.tests[test_id] = test_info
            
            # Load common test preparations
            common_tests = data.get("دليل_التحضير_والأعراض", {}).get("الفحوصات_الشائعة", [])
            
            for test in common_tests:
                test_name = test.get("الاسم", "")
                # Find existing test or create new one
                existing = self._find_test_by_name(test_name)
                
                if existing:
                    # Merge preparation info
                    existing.preparation = test.get("التحضير", "")
                    symptoms_str = test.get("الأعراض", "")
                    existing.symptoms = [s.strip() for s in symptoms_str.split("،")] if symptoms_str else []
                    existing.category = test.get("التصنيف", existing.category)
                    existing.source = "merged"
                    self.metadata["sources"]["merged"] += 1
                else:
                    # Create new test
                    test_id = f"kg_{len(self.tests) + 1:04d}"
                    symptoms_str = test.get("الأعراض", "")
                    test_info = TestInfo(
                        id=test_id,
                        name_ar=test_name,
                        preparation=test.get("التحضير", ""),
                        symptoms=[s.strip() for s in symptoms_str.split("،")] if symptoms_str else [],
                        category=test.get("التصنيف", ""),
                        source="knowledge.json"
                    )
                    self.tests[test_id] = test_info
            
            self.metadata["sources"]["knowledge.json"] = len([t for t in self.tests.values() if t.source == "knowledge.json"])
            
        except Exception as e:
            logger.error(f"❌ Error loading knowledge.json tests: {e}")
    
    def _load_excel_tests(self):
        """Load tests from Excel data"""
        try:
            with open(EXCEL_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            excel_tests = data.get("Sheet1", {}).get("data", [])
            
            for test in excel_tests:
                test_name = test.get("اسم التحليل بالعربية", "").strip()
                
                if not test_name:
                    continue
                
                # Check if test already exists
                existing = self._find_test_by_name(test_name)
                
                if existing:
                    # Merge data
                    if not existing.benefits and test.get("فائدة التحليل"):
                        existing.benefits = test.get("فائدة التحليل")
                    if not existing.preparation and test.get("التحضير قبل التحليل"):
                        existing.preparation = test.get("التحضير قبل التحليل")
                    if not existing.category and test.get("تصنيف التحليل"):
                        existing.category = test.get("تصنيف التحليل")
                    if not existing.sample_type and test.get("نوع العينة"):
                        existing.sample_type = test.get("نوع العينة")
                    if not existing.complementary_tests and test.get("التحاليل المكملة"):
                        existing.complementary_tests = test.get("التحاليل المكملة")
                    if not existing.symptoms and test.get("الأعراض"):
                        symptoms_str = test.get("الأعراض", "")
                        existing.symptoms = [s.strip() for s in symptoms_str.split("،")] if symptoms_str else []
                    
                    existing.name_en = test.get("Unnamed: 0", existing.name_en)
                    existing.source = "merged"
                else:
                    # Create new test
                    test_id = f"ex_{len(self.tests) + 1:04d}"
                    symptoms_str = test.get("الأعراض", "")
                    test_info = TestInfo(
                        id=test_id,
                        name_ar=test_name,
                        name_en=test.get("Unnamed: 0"),
                        benefits=test.get("فائدة التحليل"),
                        preparation=test.get("التحضير قبل التحليل"),
                        category=test.get("تصنيف التحليل"),
                        sample_type=test.get("نوع العينة"),
                        complementary_tests=test.get("التحاليل المكملة"),
                        symptoms=[s.strip() for s in symptoms_str.split("،")] if symptoms_str else [],
                        related_tests=[t.strip() for t in test.get("تحاليل قريبة", "").split(",") if t.strip()],
                        alternative_tests=[t.strip() for t in test.get("تحاليل بديلة", "").split(",") if t.strip()],
                        source="excel"
                    )
                    self.tests[test_id] = test_info
            
            self.metadata["sources"]["excel"] = len([t for t in self.tests.values() if t.source == "excel"])
            self.metadata["sources"]["merged"] = len([t for t in self.tests.values() if t.source == "merged"])
            
        except Exception as e:
            logger.error(f"❌ Error loading Excel tests: {e}")
    
    def _find_test_by_name(self, name: str) -> Optional[TestInfo]:
        """Find test by name (fuzzy match)"""
        name_normalized = name.strip().lower()
        
        for test in self.tests.values():
            if test.name_ar.strip().lower() == name_normalized:
                return test
            # Fuzzy match (if names are very similar)
            if name_normalized in test.name_ar.strip().lower() or test.name_ar.strip().lower() in name_normalized:
                return test
        
        return None
    
    def _build_indexes(self):
        """Build indexes for fast lookups"""
        self.tests_by_name = {}
        self.tests_by_category = {}
        
        for test in self.tests.values():
            # Index by name
            self.tests_by_name[test.name_ar.strip().lower()] = test
            
            # Index by category
            if test.category:
                category = test.category.strip()
                if category not in self.tests_by_category:
                    self.tests_by_category[category] = []
                self.tests_by_category[category].append(test)
    
    def get_test_by_name(self, name: str) -> Optional[TestInfo]:
        """Get test by exact name"""
        return self.tests_by_name.get(name.strip().lower())
    
    def search_tests(self, query: str) -> List[TestInfo]:
        """Search tests by name (fuzzy)"""
        query_lower = query.strip().lower()
        results = []
        
        for test in self.tests.values():
            if query_lower in test.name_ar.lower():
                results.append(test)
            elif test.name_en and query_lower in test.name_en.lower():
                results.append(test)
        
        return results
    
    def get_tests_by_category(self, category: str) -> List[TestInfo]:
        """Get all tests in a category"""
        return self.tests_by_category.get(category.strip(), [])
    
    def get_all_categories(self) -> List[str]:
        """Get all test categories"""
        return list(self.tests_by_category.keys())
    
    def get_ai_context(self, user_query: Optional[str] = None, max_tests: int = 12) -> str:
        """
        Get formatted context for AI system prompt (OPTIMIZED for token savings)
        
        Args:
            user_query: User's question (for smart test selection)
            max_tests: Maximum number of tests to include (reduced to 12 for cost)
        
        Returns:
            Formatted context string
        """
        context_parts = []
        
        # Company info - ESSENTIAL
        context_parts.append("=== مختبرات وريد ===")
        context_parts.append(f"{self.company_info.get('branches', '')} | فحوصات معتمدة من سباهي | زيارة منزلية مجانية")
        
        # Contact info
        contact = self.company_info.get("contact", {})
        if contact:
            context_parts.append(f"\n📞 التواصل: {contact.get('الهاتف', '')} | خدمة عملاء 24/7")
        
        # Services summary (reduced to 3 for token savings)
        context_parts.append("\n=== الخدمات الرئيسية ===")
        for service in self.services[:3]:  # Top 3 services only
            context_parts.append(f"• {service.get('الاسم', '')}")
        
        # Tests - SMART SELECTION
        if user_query:
            # Search for relevant tests
            relevant_tests = self.search_tests(user_query)[:max_tests]
        else:
            # Use most common tests
            common_categories = ["الفيتامينات", "الهرمونات والخصوبة", "الدم والتحثر", "وظائف الكبد والكلى"]
            relevant_tests = []
            for category in common_categories:
                relevant_tests.extend(self.get_tests_by_category(category)[:10])
                if len(relevant_tests) >= max_tests:
                    break
            relevant_tests = relevant_tests[:max_tests]
        
        if relevant_tests:
            context_parts.append("\n=== أسعار التحاليل ===")
            for test in relevant_tests:
                test_line = f"• {test.name_ar}"
                if test.price:
                    test_line += f": {test.price}"
                context_parts.append(test_line)
        
        # Test preparation - TOP 3 ONLY (reduced for token savings)
        tests_with_prep = [t for t in self.tests.values() if t.preparation][:3]
        if tests_with_prep:
            context_parts.append("\n=== تحضير الفحوصات (أمثلة) ===")
            for test in tests_with_prep:
                context_parts.append(f"• {test.name_ar}: {test.preparation[:80]}...")
        
        return "\n".join(context_parts)
    
    def save_unified_knowledge(self):
        """Save unified knowledge base to JSON file"""
        try:
            unified_data = {
                "metadata": self.metadata,
                "company": self.company_info,
                "services": self.services,
                "tests": [test.to_dict() for test in self.tests.values()]
            }
            
            with open(UNIFIED_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(unified_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ Saved unified knowledge base: {UNIFIED_JSON_PATH}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error saving unified knowledge: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        return {
            "total_tests": self.metadata["total_tests"],
            "sources": self.metadata["sources"],
            "categories": len(self.tests_by_category),
            "services": len(self.services),
            "tests_with_prices": len([t for t in self.tests.values() if t.price]),
            "tests_with_preparation": len([t for t in self.tests.values() if t.preparation]),
            "tests_with_symptoms": len([t for t in self.tests.values() if t.symptoms])
        }


# Create global instance
integrated_knowledge = IntegratedKnowledgeBase()


# Convenience functions
def get_test(name: str) -> Optional[TestInfo]:
    """Get test by name"""
    return integrated_knowledge.get_test_by_name(name)


def search_tests(query: str) -> List[TestInfo]:
    """Search tests"""
    return integrated_knowledge.search_tests(query)


def get_knowledge_context(user_query: Optional[str] = None) -> str:
    """Get AI context"""
    return integrated_knowledge.get_ai_context(user_query)


if __name__ == "__main__":
    # Test the integration
    print("=" * 60)
    print("Testing Knowledge Base Integration")
    print("=" * 60)
    
    # Print stats
    stats = integrated_knowledge.get_stats()
    print("\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Test search
    print("\n\nTest Search: 'فيتامين د'")
    results = search_tests("فيتامين د")
    for test in results[:3]:
        print(f"  - {test.name_ar} ({test.price}) [{test.source}]")
    
    # Test get by name
    print("\n\nTest Get by Name: 'تحليل فيتامين د'")
    test = get_test("تحليل فيتامين د")
    if test:
        print(f"  Found: {test.name_ar} - {test.price}")
        print(f"  Category: {test.category}")
        print(f"  Preparation: {test.preparation[:100] if test.preparation else 'N/A'}...")
    
    # Save unified knowledge
    print("\n\nSaving unified knowledge base...")
    if integrated_knowledge.save_unified_knowledge():
        print("✅ Success!")
    
    print("\n" + "=" * 60)
