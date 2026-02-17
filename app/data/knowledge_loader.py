"""
Knowledge Base Loader Module
Handles loading and querying the medical knowledge base
"""

import json
import os
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Path to knowledge base file
KNOWLEDGE_BASE_PATH = os.path.join(
    os.path.dirname(__file__),
    "knowledge.json"
)


class KnowledgeBase:
    """
    Knowledge Base manager for Wareed Medical Assistant
    Loads and provides access to company and medical information
    """
    
    def __init__(self):
        """Initialize and load the knowledge base"""
        self.data = None
        self.load()
    
    def load(self) -> bool:
        """
        Load knowledge base from JSON file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(KNOWLEDGE_BASE_PATH, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            logger.info("✅ Knowledge base loaded successfully")
            return True
        except FileNotFoundError:
            logger.error(f"❌ Knowledge base file not found: {KNOWLEDGE_BASE_PATH}")
            self.data = {}
            return False
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in knowledge base: {str(e)}")
            self.data = {}
            return False
        except Exception as e:
            logger.error(f"❌ Error loading knowledge base: {str(e)}")
            self.data = {}
            return False
    
    def get_company_info(self) -> Optional[Dict[str, Any]]:
        """Get company information"""
        return self.data.get("الشركة")
    
    def get_mission(self) -> Optional[str]:
        """Get company mission"""
        return self.data.get("الرسالة")
    
    def get_vision(self) -> Optional[str]:
        """Get company vision"""
        return self.data.get("الرؤية")
    
    def get_services(self) -> Optional[List[Dict[str, str]]]:
        """Get list of services"""
        return self.data.get("الخدمات", [])
    
    def get_service_by_name(self, service_name: str) -> Optional[Dict[str, str]]:
        """
        Get a specific service by name
        
        Args:
            service_name: Name of the service (in Arabic)
            
        Returns:
            Service information or None if not found
        """
        services = self.get_services()
        for service in services:
            if service_name.lower() in service.get("الاسم", "").lower():
                return service
        return None
    
    def get_contact_info(self) -> Optional[Dict[str, str]]:
        """Get contact information"""
        return self.data.get("معلومات_الاتصال")
    
    def get_test_types(self) -> Optional[List[Dict[str, str]]]:
        """Get available test/examination types"""
        return self.data.get("أنواع_الفحوصات", [])
    
    def get_features(self) -> Optional[List[str]]:
        """Get company features/advantages"""
        return self.data.get("المميزات", [])
    
    def get_core_values(self) -> Optional[List[str]]:
        """Get core values"""
        return self.data.get("القيم_الأساسية", [])
    
    def search_knowledge(self, query: str) -> str:
        """
        Search the knowledge base for relevant information
        
        Args:
            query: Search query (can be in Arabic or English)
            
        Returns:
            Formatted string with relevant information
        """
        query_lower = query.lower()
        results = []
        
        # Search in services
        if any(word in query_lower for word in ['خدمة', 'خدمات', 'service', 'تحليل', 'فحص']):
            services = self.get_services()
            if services:
                results.append("الخدمات المتاحة:")
                for service in services:
                    results.append(f"- {service['الاسم']}: {service['الوصف']}")
        
        # Search for contact info
        if any(word in query_lower for word in ['اتصال', 'تواصل', 'رقم', 'هاتف', 'contact', 'phone']):
            contact = self.get_contact_info()
            if contact:
                results.append(f"\nمعلومات الاتصال:")
                results.append(f"- الهاتف: {contact.get('الهاتف')}")
                results.append(f"- البريد الإلكتروني: {contact.get('البريد_الإلكتروني')}")
        
        # Search for company info
        if any(word in query_lower for word in ['شركة', 'وريد', 'company', 'about', 'من نحن']):
            company = self.get_company_info()
            if company:
                results.append(f"\nعن الشركة:")
                results.append(company.get('الوصف', ''))
        
        # Search for branches
        if any(word in query_lower for word in ['فرع', 'فروع', 'مكان', 'موقع', 'branch', 'location']):
            company = self.get_company_info()
            if company:
                results.append(f"\nالفروع: {company.get('عدد_الفروع')}")
                results.append(f"المناطق: {company.get('المناطق')}")
        
        return "\n".join(results) if results else ""
    
    def get_context_for_ai(self) -> str:
        """
        Get formatted context string to inject into AI prompts (COMPACT VERSION)
        
        Returns:
            Formatted string with ESSENTIAL information only to reduce tokens
        """
        context_parts = []
        
        # Company info - MINIMAL
        context_parts.append("=== مختبرات وريد ===")
        context_parts.append("أكثر من 40 فرع في المملكة | فحوصات معتمدة من سباهي | زيارة منزلية مجانية")
        
        # Contact - ESSENTIAL ONLY
        contact = self.get_contact_info()
        if contact:
            context_parts.append(f"\n📞 التواصل: {contact.get('الهاتف')} | خدمة عملاء 24/7")
        
        # Services - SUMMARY ONLY
        context_parts.append("\n=== الخدمات الرئيسية ===")
        context_parts.append("• تحليل Inbody (دقائق)")
        context_parts.append("• زيارة منزلية مجانية")
        context_parts.append("• خدمة عملاء 24 ساعة")
        context_parts.append("• استشارة طبية وشرح النتائج")
        context_parts.append("• قياس الضغط مجاني")
        
        # PRICES - MOST COMMON TESTS ONLY (TOP 25)
        packages = self.data.get('الباقات_والتحاليل', {})
        individual_tests = packages.get('التحاليل_الفردية', {})
        if individual_tests and individual_tests.get('التحاليل'):
            context_parts.append("\n=== أسعار التحاليل الشائعة ===")
            context_parts.append("(أسعار تبدأ من 17 ريال)")
            # Only include TOP 25 most common tests
            common_test_names = [
                'فيتامين د', 'فيتامين ب12', 'السكر التراكمي', 'الحديد', 
                'الكوليسترول', 'الكرياتينين', 'جرثومة المعدة', 'السكر',
                'الكالسيوم', 'المغنيسيوم', 'النقرس', 'الفسفور', 'النحاس',
                'فيتامين C', 'تشبع الحديد', 'وظيفة الكبد', 'حساسية الطعام',
                'حساسية المستنشقات', 'هرمون التبويض', 'هرمون التستوستيرون',
                'هرمون البروستات', 'الألبومين', 'الجلوبيولين', 'الأميليز', 'Lipase'
            ]
            for test in individual_tests.get('التحاليل', []):
                test_name = test.get('الاسم', '')
                # Check if test is in common list
                if any(common in test_name for common in common_test_names):
                    context_parts.append(f"• {test_name}: {test.get('السعر')}")
        
        # Test Preparation - TOP 8 ONLY
        test_guide = self.data.get('دليل_التحضير_والأعراض', {})
        common_tests = test_guide.get('الفحوصات_الشائعة', [])
        if common_tests:
            context_parts.append("\n=== تحضير الفحوصات (الشائعة) ===")
            # Only include TOP 8 most requested tests
            for test in common_tests[:8]:
                context_parts.append(f"• {test.get('الاسم')}: {test.get('التحضير')}")
        
        return "\n".join(context_parts)
    
    def get_test_preparation_info(self, test_name: str) -> Optional[Dict[str, Any]]:
        """
        Get preparation and symptoms information for a specific test
        
        Args:
            test_name: Name of the test (in Arabic)
            
        Returns:
            Test information or None if not found
        """
        test_guide = self.data.get('دليل_التحضير_والأعراض', {})
        
        # Search in common tests
        common_tests = test_guide.get('الفحوصات_الشائعة', [])
        for test in common_tests:
            if test_name.lower() in test.get('الاسم', '').lower():
                return test
        
        # Search in advanced tests
        advanced_tests = test_guide.get('الفحوصات_المتقدمة_والنادرة', [])
        for test in advanced_tests:
            if test_name.lower() in test.get('الاسم', '').lower():
                return test
        
        return None
    
    def reload(self):
        """Reload the knowledge base from file"""
        self.load()


# Create global instance
knowledge_base = KnowledgeBase()


# Convenience functions
def get_knowledge_context() -> str:
    """Get knowledge base context for AI"""
    return knowledge_base.get_context_for_ai()


def search_knowledge(query: str) -> str:
    """Search knowledge base"""
    return knowledge_base.search_knowledge(query)


def get_services_list() -> List[Dict[str, str]]:
    """Get list of all services"""
    return knowledge_base.get_services() or []


def get_contact_details() -> Dict[str, str]:
    """Get contact information"""
    return knowledge_base.get_contact_info() or {}
