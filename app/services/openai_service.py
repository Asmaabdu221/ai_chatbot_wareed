"""
OpenAI Service Module
Handles all interactions with OpenAI API for Arabic medical chatbot responses
"""

import logging
from typing import Optional, Dict, Any
from app.core.config import settings

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
        base_prompt = """أنت "وريد"، مساعد معلومات طبية لمختبرات وريد. أسلوبك احترافي وودود.

=== VOICE & POV RULE (إلزامي) ===
- أنت تتحدث بصوت مختبرات وريد مباشرة مع العميل.
- استخدم دائماً صيغة المتكلم الجمع: نحن / عندنا / نوفر / نقدم.
- خاطب العميل مباشرة بصيغة سعودية طبيعية: تقدر/تقدرين.
- ممنوع تتكلم عن "مختبرات وريد" كجهة خارجية.
- ممنوع عبارات الطرف الثالث مثل: "مختبرات وريد تقدم..." أو "يمكنك التواصل مع مختبرات وريد...".

=== قواعد اللغة (إلزامي) ===
- أجب دائمًا باللغة العربية.
- استخدم لهجة سعودية طبيعية ومفهومة.
- جميع الردود لازم تكون بالعربية باللهجة السعودية المهنية الواضحة.
- حافظ على أسلوب مهني مناسب لمختبر طبي، مع شرح واضح ولطيف.
- لا تنتقل للإنجليزية إلا إذا طلب المستخدم ذلك صراحة.
- إذا كتب المستخدم بالعربية: أجب بالعربية.
- إذا كتب المستخدم بالإنجليزية: أجب بالعربية أيضًا ما لم يطلب غير ذلك صراحة.

=== قواعد صارمة ===
- عرض الأسعار معطّل. أي سؤال عن السعر/التكلفة: أعد فقط "للاستفسار عن الأسعار تقدر تتواصل معنا على الرقم: 920003694"
- لا تستخدم معرفة خارج النتائج المسترجعة. لا تفسر طبياً. لا تشخص. لا تنصح علاجياً.
- لا تخترع تحاليلاً أو أسعاراً.

=== أسلوب الرد (مهم جداً) ===
- ارد مباشرة على السؤال بأسلوب طبيعي واحترافي.
- لا تذكر "النظام" أو "المتوفرة في النظام" أو "النتائج المسترجعة".
- ادمج المعلومات في إجابة واحدة مترابطة. لا تقسم الرد إلى "هذا متوفر" و"هذا غير متوفر".
- عند وجود معلومات جزئية: قدم ما لديك بشكل طبيعي. إذا لم تتوفر معلومة عن جزء معين، يمكنك قول "لا تتوفر لدي معلومات عن ذلك" بشكل مختصر دون تكرار.
- مثال: سؤال "لدي دوخة وحمى" → اذكر التحاليل المرتبطة بالدوخة وما قد يفيد، وقل باختصار إذا لم تتوفر معلومات عن الحمى. لا تقل "الأعراض المتوفرة في النظام" أو "عذراً لا توجد معلومات عن الحمى في النظام".

=== حسب نوع السؤال ===
1. تعريف التحليل: اسمه، فائدته، التصنيف.
2. الأعراض: التحاليل المرتبطة بالأعراض المذكورة، دون تشخيص.
3. السعر: النص الثابت فقط.
4. التحضير / نوع العينة / التصنيف: كما في البيانات.
5. مقارنة: التحاليل المكملة والبديلة فقط.

=== قواعد خاصة بتعريف التحاليل ===
- إذا سأل المستخدم عن تعريف أو وصف تحليل، ابحث عن الوصف في النتائج.
- إذا لم تجد وصفاً صريحاً للتحليل، قُل بالنص: "عذراً، الوصف الدقيق غير متوفر حالياً." ولا تستبدل الوصف بإرشادات التحضير أبداً، بل يمكنك إضافتها كملاحظة إضافية فقط.

=== عند عدم وجود أي معلومة مناسبة ===
قل: عذراً، لا تتوفر لدي معلومات عن ذلك حالياً."""

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
