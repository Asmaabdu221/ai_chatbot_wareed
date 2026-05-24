"""
OpenAI Service Module
Handles all interactions with OpenAI API for Arabic medical chatbot responses
"""

import logging
from typing import Optional, Dict, Any
from app.core.config import settings
from app.config.constants import PHONE_NUMBER

try:
    from openai import OpenAI, OpenAIError
except Exception:  # Keep backend running even if OpenAI package runtime is broken.
    OpenAI = None

    class OpenAIError(Exception):
        pass

# Get logger
logger = logging.getLogger(__name__)


class OpenAIService:
    """
    Service class to interact with OpenAI API
    Provides methods for generating Arabic medical chatbot responses
    """
    
    def __init__(self):
        """
        Initialize OpenAI client with API key from settings
        """
        try:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY) if OpenAI is not None else None
            self.model = settings.OPENAI_MODEL
            self.max_tokens = settings.OPENAI_MAX_TOKENS
            self.temperature = min(0.1, float(getattr(settings, "OPENAI_TEMPERATURE", 0.0)))
            if self.client is not None:
                logger.info(f"✅ OpenAI Service initialized with model: {self.model}")
            else:
                logger.warning("⚠️ OpenAI runtime is unavailable; fallback responses will be used.")
        except Exception as e:
            self.client = None
            self.model = settings.OPENAI_MODEL
            self.max_tokens = settings.OPENAI_MAX_TOKENS
            self.temperature = min(0.1, float(getattr(settings, "OPENAI_TEMPERATURE", 0.0)))
            logger.error(f"❌ Failed to initialize OpenAI Service: {str(e)}")
    
    def _build_system_prompt(self, knowledge_context: Optional[str] = None) -> str:
        """
        Build system prompt for retrieval-only medical info server.
        No generation, no inference, no medical fatwa. Grounded in RAG only.
        """
        base_prompt = """أنت "وريد"، مساعد مختبرات وريد الطبية الذكي. شخصيتك: دافئ، سعودي، مختصر، ومفيد. تكلّم العميل بلهجة سعودية خليجية طبيعية، وكأنك موظف استقبال ذكي في مختبر راقٍ — مو روبوت. استخدم صيغة "نحن/عندنا/نوفّر" وخاطب العميل بـ تقدر/تقدرين.

## طول الرد (مهم جداً):
- التحية: جملة واحدة فقط.
- سؤال عن تحليل: من ٣ إلى ٥ أسطر كحد أقصى.
- الأعراض: اذكر ٣ تحاليل + جملة دعوة واحدة.
- الفروع: اسم الفرع وموقعه فقط.
- إذا ما تعرف: جملة واحدة + رقم الهاتف. لا تطوّل ولا تكرّر.

## قواعد صارمة جداً للالتزام بالمصدر — لا استثناء:
- استخدم فقط المعلومات الموجودة في النتائج المسترجعة، ولا تضف شيئاً من خارجها. إذا المعلومة غير موجودة قل: "ما عندي هذي المعلومة، تواصل مع فريقنا على 8001221220".
- لا تذكر الأسعار إطلاقاً؛ السعر يُعطى فقط بعد مشاركة رقم الجوال. لأي سؤال عن السعر قل: "تبي تعرف السعر وتحجز؟ اكتب رقمك".
- لا تشخّص ولا تصف علاجاً. أي نتيجة تحتاج تفسير قل: "لازم طبيبك يفسّر نتيجتك بدقة".
- لا تتحدث عن منافسين (مختبر أو مستشفى آخر): "أقدر أساعدك فقط في خدمات مختبرات وريد".
- إذا كانت النتائج المسترجعة فارغة: "ما عندي معلومات عن هذا الموضوع، تواصل معنا على 8001221220".
- المواضيع غير الطبية (سياسة، دين، رياضة، معلومات عامة): "هذا خارج تخصصي، أنا متخصص في تحاليل وريد".

## قوالب الردود:
- تحية: "أهلاً وسهلاً! 👋 أنا وريد، كيف أقدر أساعدك اليوم؟"
- سعر/تعريف تحليل: "تحليل [الاسم] متوفر عندنا ✅ [معلومة مفيدة واحدة من النتائج]. تبي تعرف السعر وتحجز؟ اكتب رقمك 📞"
- أعراض: "أعراضك تحتاج انتباه 🩺 أنصحك بـ: ١. [تحليل] ٢. [تحليل] ٣. [تحليل]. اكتب رقمك وفريقنا يرتب لك كل شيء"
- صيام: "[نعم/لا]، [التحليل] [يحتاج/ما يحتاج] صيام ✅ [التعليمات بجملة واحدة]"
- تفسير نتيجة: "[القيمة] [طبيعية/تحتاج متابعة] بشكل عام. ⚠️ هذي معلومة إرشادية — لازم طبيبك يفسّر نتيجتك بدقة. تبي نساعدك أكثر؟ اكتب رقمك 📞"
- خارج التخصص/لا معلومة: "هذا خارج تخصصي 😅 أنا متخصص في تحاليل وريد — ممكن أساعدك فيها؟ أو تتصل على 📞 8001221220"

## أمثلة:
العميل: مرحبا
وريد: أهلاً وسهلاً! 👋 أنا وريد، كيف أقدر أساعدك اليوم؟

العميل: كم سعر تحليل السكر التراكمي؟
وريد: تحليل السكر التراكمي (HbA1c) متوفر عندنا ✅ يعطيك متوسط مستوى السكر في آخر ٣ أشهر. تبي تعرف السعر وتحجز؟ اكتب رقمك 📞

العميل: عندي تعب وصداع مستمر
وريد: أعراضك تحتاج انتباه 🩺 أنصحك بـ: ١. صورة دم كاملة (CBC) ٢. مخزون الحديد (Ferritin) ٣. هرمون الغدة الدرقية (TSH). اكتب رقمك وفريقنا يرتب لك كل شيء.

العميل: ما هو علاج ارتفاع الضغط؟
وريد: هذا خارج تخصصي 😅 أنا متخصص في تحاليل وريد — ممكن أساعدك فيها؟ أو تتصل على 📞 8001221220"""

        base_prompt = base_prompt.replace("8001221220", PHONE_NUMBER)

        if knowledge_context:
            base_prompt += f"\n\n=== النتائج المسترجعة (استخدمها فقط - لا تضيف شيئاً من خارجها) ===\n{knowledge_context}"
        
        return base_prompt
    
    def generate_response(
        self,
        user_message: str,
        knowledge_context: Optional[str] = None,
        conversation_history: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Generate a response from OpenAI API
        
        Args:
            user_message: User's question/message in Arabic or English
            knowledge_context: Optional medical knowledge context
            conversation_history: Optional list of previous messages for context
            
        Returns:
            Dictionary containing response and metadata
            {
                "success": bool,
                "response": str,
                "model": str,
                "tokens_used": int,
                "error": Optional[str]
            }
        """
        try:
            if self.client is None:
                return {
                    "success": False,
                    "response": "حالياً خدمة الذكاء الاصطناعي عندنا غير متاحة بشكل مؤقت، وبنخدمك بالمعلومة المتوفرة من قاعدة المعرفة.",
                    "model": self.model,
                    "tokens_used": 0,
                    "error": "OpenAI runtime unavailable",
                }
            logger.info(f"📨 Generating response for message: {user_message[:50]}...")
            
            # Build messages array
            messages = [
                {"role": "system", "content": self._build_system_prompt(knowledge_context)}
            ]
            
            # Add conversation history if provided
            if conversation_history:
                messages.extend(conversation_history)
            
            # Add current user message
            messages.append({"role": "user", "content": user_message})
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            # Extract response
            ai_response = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            
            # Calculate cost (gpt-3.5-turbo pricing)
            cost = (input_tokens * 0.0005 / 1000) + (output_tokens * 0.0015 / 1000)
            
            logger.info(f"✅ Response generated - Tokens: {tokens_used} (in:{input_tokens}, out:{output_tokens}) - Cost: ${cost:.4f}")
            
            return {
                "success": True,
                "response": ai_response,
                "model": self.model,
                "tokens_used": tokens_used,
                "error": None
            }
            
        except OpenAIError as e:
            error_msg = f"OpenAI API Error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "response": "عذراً، واجهنا خطأ في الاتصال بخدمة الذكاء الاصطناعي. نرجو المحاولة مرة ثانية.",
                "model": self.model,
                "tokens_used": 0,
                "error": error_msg
            }
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "response": "عذراً، واجهنا خطأ غير متوقع. نرجو المحاولة مرة ثانية لاحقاً.",
                "model": self.model,
                "tokens_used": 0,
                "error": error_msg
            }
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the OpenAI API connection
        
        Returns:
            Dictionary with connection test results
        """
        try:
            if self.client is None:
                return {
                    "success": False,
                    "message": "OpenAI runtime unavailable",
                    "response": None,
                    "model": self.model,
                }
            logger.info("🔍 Testing OpenAI API connection...")
            
            # Simple test message
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say 'تم الاتصال بنجاح' in Arabic"}
                ],
                max_tokens=50,
                temperature=0.5
            )
            
            result = response.choices[0].message.content
            logger.info(f"✅ Connection test successful: {result}")
            
            return {
                "success": True,
                "message": "OpenAI API connection successful",
                "response": result,
                "model": self.model
            }
            
        except OpenAIError as e:
            error_msg = f"OpenAI API connection failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "message": error_msg,
                "response": None,
                "model": self.model
            }
        
        except Exception as e:
            error_msg = f"Connection test failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "message": error_msg,
                "response": None,
                "model": self.model
            }


# Create a global instance of the service
openai_service = OpenAIService()


# Convenience function for quick access
def get_ai_response(
    user_message: str,
    knowledge_context: Optional[str] = None,
    conversation_history: Optional[list] = None
) -> Dict[str, Any]:
    """
    Convenience function to get AI response
    
    Args:
        user_message: User's message
        knowledge_context: Optional medical knowledge
        conversation_history: Optional conversation history
        
    Returns:
        Response dictionary
    """
    return openai_service.generate_response(
        user_message=user_message,
        knowledge_context=knowledge_context,
        conversation_history=conversation_history
    )
