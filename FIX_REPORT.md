# Wareed AI Lead Pipeline & Conversation Fixes — Report

## 1. Fixed Issues

- **Lead pipeline**: **FIXED**. Leads are now successfully persisted to the database via `create_lead_from_draft` and an attempt is made to deliver them to the configured webhook via `deliver_lead`.
- **Routing decision**: **FIXED**. Both the price flow and general runtime results now reliably update the `ConversationDecision` AFTER the `runtime_router` has executed, ensuring that contextual follow-ups like `ASK_PHONE` are triggered correctly for paths like `tests_business_price`.
- **RAG fallback**: **FIXED**. When the system is RAG-ready but no high-similarity documents are found, it no longer defaults straight to `NO_INFO`. Instead, the LLM is prompted strictly to attempt answering the question before giving up.
- **Selection bug**: **FIXED**. Cross-domain persistence memory is now correctly cleared when the user switches to a different feature (e.g. going from inquiring about branches to tests). Old menu choices like "1" will no longer inadvertently trigger a selection from an unrelated context.
- **Price flow**: **FIXED**. The price query logic now renders the price response text to the user FIRST, and only appends the "ask phone" Call-to-Action text below it.

## 2. What Changed

* **`app/services/conversation_manager.py`**
  * Updated `_check_urgent_transfer` to recognize `_CUSTOMER_SERVICE_RE` explicitly. It now accurately flags requests matching phrases like "أبغى أتواصل مع خدمة العملاء" as `TRANSFER_TO_HUMAN` to immediately jump to lead/phone capture.
* **`app/api/chat.py`**
  * Added LLM fallback call logic in the RAG routine before giving up and returning `NO_INFO_MESSAGE`. 
  * Re-run `decide_conversation_action` right after `route_runtime_message`.
* **`app/services/conversation_flow.py`** & **`app/services/lead_service.py`**
  * Added lead extraction logic and `deliver_lead` execution into the endpoints so that the lead is successfully logged into SQLite, tracked, and delivered.
* **`tests/test_conversation_flows.py`**
  * Cleaned corrupted file contents that prevented `pytest` execution. 

## 3. Before vs After Behavior

| Scenario | Before | After |
| :--- | :--- | :--- |
| **User asks for Price ("سعر")** | Triggered `ASK_PHONE` immediately, often hiding the price until they answered or skipping it entirely. | The cost/price is provided directly, with `ASK_PHONE` appended *at the end* of the price reply. |
| **"تواصل مع خدمة العملاء" (Talk to CS)** | Was marked as `OFFER_HUMAN_HELP`, gently offering help without strictly capturing the phone correctly. | Is now flagged as `TRANSFER_TO_HUMAN`, actively routing to the `AWAITING_PHONE` state to secure a solid lead capture. |
| **Switching Context + typing "1"** | Maintained previous `selection_state`, mapping "1" to a branch even when the user just jumped to asking about a test. | Cross-domain switches detect a change in `runtime_source` context and immediately `clear_selection_state` to prevent ghost inputs. |
| **RAG fails to hit threshold** | Jumped immediately to `NO_INFO` message ("لا أملك معلومات..."). | Passes through an LLM fallback layer with a strict prompt structure to answer confidently if capable, else defaults to `NO_INFO`. |
| **Phone number is provided** | Phone detected but lead often not saved or delivered via `lead_service`. | Draft -> SQLite Lead -> Webhook Delivery -> Marking Delivered/Failed properly operates under `process_phone_submission`. |

## 4. Remaining Risks

* **Strict Prompt LLM Hallucinations**: We've added an LLM fallback if RAG strict threshold isn't met. Although it's prompted very strictly not to hallucinate ("أجب فقط إذا كنت متأكداً"), LLMs can occasionally present generated context plausibly. Periodic monitoring of its outputs vs the true KB ensures safety remains intact.
* **Leads Delivery Pipeline Webhooks**: The `INTERNAL_LEADS_WEBHOOK_URL` behaves as a "stub delivery/mock mode" when empty/failing. While leads are successfully gathered into the SQLite `leads` table, they will need the correct environment variable configurations to actually reach external sales CRMs properly in Production.
