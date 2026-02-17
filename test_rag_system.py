"""
Complete RAG System Test
=========================
اختبار شامل لنظام RAG الجديد

Author: Smart Coding Assistant  
Date: 2026-02-05
"""

import requests
import json
from datetime import datetime

# API Configuration
BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/api"

print("="*70)
print("🧪 Complete RAG System Test - Wareed Medical Chatbot")
print("="*70)
print()

# Test scenarios
test_scenarios = [
    {
        "name": "سؤال عن الأعراض",
        "message": "عندي تعب وإرهاق شديد، ما التحاليل المناسبة؟",
        "expected": "يجب أن يقترح تحاليل الحديد، الدم الشامل، أو الهرمونات"
    },
    {
        "name": "سؤال عن السعر",
        "message": "كم سعر تحليل السكر؟",
        "expected": "يجب أن يذكر سعر تحليل السكر"
    },
    {
        "name": "سؤال عام (FAQ)",
        "message": "هل تقدمون خدمة زيارة منزلية؟",
        "expected": "يجب أن يجيب من FAQs"
    },
    {
        "name": "سؤال عن التحضير",
        "message": "هل تحليل الدهون يحتاج صيام؟",
        "expected": "يجب أن يذكر معلومات الصيام"
    },
    {
        "name": "سؤال طبي (خارج النطاق)",
        "message": "كيف أعالج الصداع؟",
        "expected": "يجب أن يرفض ويوجه لطبيب مختص"
    }
]

def test_health_check():
    """Test 1: Health Check"""
    print("📊 Test 1: Health Check")
    print("-"*70)
    
    try:
        response = requests.get(f"{API_URL}/chat/health")
        data = response.json()
        
        print(f"✅ Status: {data['status']}")
        print(f"✅ OpenAI Connected: {data['openai_connected']}")
        print(f"✅ Knowledge Base Loaded: {data['knowledge_base_loaded']}")
        print()
        
        return data['status'] == 'healthy'
    
    except Exception as e:
        print(f"❌ Health check failed: {str(e)}")
        print()
        return False


def test_statistics():
    """Test 2: Knowledge Base Statistics"""
    print("📊 Test 2: Knowledge Base Statistics")
    print("-"*70)
    
    try:
        response = requests.get(f"{API_URL}/chat/stats")
        data = response.json()
        
        if data['success']:
            stats = data['statistics']
            print(f"✅ Total Tests: {stats['total_tests']}")
            print(f"✅ Total FAQs: {stats['total_faqs']}")
            print(f"✅ Tests with Price: {stats['tests_with_price']}")
            print(f"✅ Categories: {stats['categories']}")
            print(f"✅ Price Range: {stats['price_range']['min']:.0f} - {stats['price_range']['max']:.0f} SAR")
            print(f"✅ Version: {stats['version']}")
            print()
            return True
        else:
            print("❌ Failed to get statistics")
            print()
            return False
    
    except Exception as e:
        print(f"❌ Statistics test failed: {str(e)}")
        print()
        return False


def test_chat_scenarios():
    """Test 3: Chat Scenarios with RAG"""
    print("📊 Test 3: Chat Scenarios with RAG")
    print("-"*70)
    
    results = []
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n🔹 Scenario {i}: {scenario['name']}")
        print(f"💬 User: {scenario['message']}")
        print()
        
        try:
            response = requests.post(
                f"{API_URL}/chat",
                json={
                    "message": scenario['message'],
                    "include_knowledge": True
                }
            )
            
            data = response.json()
            
            if data['success']:
                print(f"🤖 Assistant: {data['reply'][:200]}...")
                print()
                print(f"📊 Tokens Used: {data['tokens_used']}")
                print(f"🤖 Model: {data['model']}")
                print(f"✅ Expected: {scenario['expected']}")
                print("-"*70)
                
                results.append({
                    'scenario': scenario['name'],
                    'success': True,
                    'tokens': data['tokens_used']
                })
            else:
                print(f"❌ Error: {data['error']}")
                print("-"*70)
                
                results.append({
                    'scenario': scenario['name'],
                    'success': False,
                    'error': data['error']
                })
        
        except Exception as e:
            print(f"❌ Request failed: {str(e)}")
            print("-"*70)
            
            results.append({
                'scenario': scenario['name'],
                'success': False,
                'error': str(e)
            })
    
    print()
    return results


def main():
    """Run all tests"""
    print(f"⏰ Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test 1: Health Check
    health_ok = test_health_check()
    
    if not health_ok:
        print("⚠️ Health check failed! Make sure the server is running.")
        print("   Run: uvicorn app.main:app --reload")
        return
    
    # Test 2: Statistics
    stats_ok = test_statistics()
    
    # Test 3: Chat Scenarios
    results = test_chat_scenarios()
    
    # Summary
    print()
    print("="*70)
    print("📊 Test Summary")
    print("="*70)
    
    successful = sum(1 for r in results if r['success'])
    total = len(results)
    
    print(f"\n✅ Successful: {successful}/{total}")
    print(f"❌ Failed: {total - successful}/{total}")
    
    if successful == total:
        print("\n🎉 All tests passed! RAG system is working correctly!")
    else:
        print("\n⚠️ Some tests failed. Check the logs above.")
    
    print()
    print(f"⏰ Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


if __name__ == "__main__":
    print("\n⚠️ Make sure the server is running before testing!")
    print("   Run in another terminal: uvicorn app.main:app --reload")
    print()
    
    input("Press Enter to start testing...")
    print()
    
    main()
