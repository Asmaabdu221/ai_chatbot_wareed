import axios from "axios";
import { getAccessToken } from "./auth";

const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL ||
  "https://ai-chatbot-wareed.onrender.com";

const getApiUrlForDisplay = () => API_BASE_URL;

export { API_BASE_URL, getApiUrlForDisplay };

console.log("[API] Base URL:", API_BASE_URL);

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

const isDev = process.env.NODE_ENV === "development";

api.interceptors.request.use((config) => {
  const url = config?.url || "";
  const token = getAccessToken();
  if (config.data instanceof FormData) {
    delete config.headers["Content-Type"];
  }
  if (token && !config.headers?.Authorization) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (
    isDev &&
    (url.includes("/api/auth/") || url.includes("/api/chat") || url.includes("/api/conversations"))
  ) {
    console.info("[API] Request:", {
      method: config.method,
      baseURL: config.baseURL,
      url: config.url,
      headers: config.headers,
      data: config.data,
    });
  }
  return config;
});

let onUnauthorized = () => {};
export function setOnUnauthorized(callback) {
  onUnauthorized = callback || (() => {});
}

// 🔴 Very important: interceptor to log the real error
api.interceptors.response.use(
  (response) => {
    if (isDev && response?.config?.url?.includes("/api/auth/")) {
      console.info("[API] Response:", {
        status: response.status,
        url: response.config?.url,
        data: response.data,
      });
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      onUnauthorized();
    }
    console.error("AXIOS ERROR FULL:", {
      message: error.message,
      code: error.code,
      config: error.config,
      response: error.response,
    });
    return Promise.reject(error);
  }
);

export const checkAPIHealth = async () => {
  try {
    const response = await api.get("/api/health", { timeout: 5000 });
    return response.data.api_status === 'healthy';
  } catch (error) {
    console.error('API health check failed:', error);
    return false;
  }
};

/** Auth: login (email, password) -> { access_token, refresh_token } */
export const login = async (email, password) => {
  const { data } = await api.post("/api/auth/login", { email, password }, { timeout: 30000 });
  return data;
};

/** Auth: register (email, password) -> { access_token, refresh_token } */
export const register = async (email, password) => {
  const { data } = await api.post("/api/auth/register", { email, password }, { timeout: 30000 });
  return data;
};

/** Auth: current user (requires Bearer) */
export const getMe = async () => {
  const token = getAccessToken();
  const { data } = await api.get("/api/auth/me", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return data;
};

/** Update profile (display_name, username) */
export const updateProfile = async (displayName, username) => {
  const token = getAccessToken();
  const body = {};
  if (displayName !== undefined) body.display_name = displayName;
  if (username !== undefined) body.username = username;
  const { data } = await api.patch("/api/auth/profile", body, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return data;
};

/** Upload profile avatar image */
export const uploadAvatar = async (file) => {
  const token = getAccessToken();
  const formData = new FormData();
  formData.append("file", file, file.name || "avatar.jpg");
  const response = await api.post("/api/auth/profile/avatar", formData, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    timeout: 30000,
  });
  console.log("[Avatar Upload] response:", {
    status: response.status,
    data: response.data,
  });
  return response.data;
};

/**
 * Send chat message (legacy /api/chat - works with or without auth)
 */
export const sendChatMessage = async (message, userId = null, conversationId = null, includeKnowledge = true) => {
  try {
    const response = await api.post("/api/chat", {
      message,
      user_id: userId,
      conversation_id: conversationId,
      include_knowledge: includeKnowledge,
    });
    return response.data;
  } catch (error) {
    if (error.response) {
      const detail = error.response.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : (Array.isArray(detail) && detail[0]?.msg) || 'Server error';
      throw new Error(msg);
    } else if (error.request) {
      throw new Error(`لا يمكن الاتصال بالخادم. تأكد من تشغيل الخادم على ${getApiUrlForDisplay()}`);
    }
    throw new Error('حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.');
  }
};

/**
 * List my conversations (JWT only, no user_id)
 */
export const getUserConversations = async () => {
  const token = getAccessToken();
  const response = await api.get("/api/conversations", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return response.data;
};

/**
 * Create conversation (optional title). Returns new conversation.
 */
export const createConversation = async (title = null) => {
  const token = getAccessToken();
  const response = await api.post(
    "/api/conversations",
    title != null ? { title } : {},
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 30000,
    }
  );
  return response.data;
};

/**
 * Get one conversation (by id)
 */
export const getConversation = async (conversationId) => {
  const token = getAccessToken();
  const response = await api.get(`/api/conversations/${conversationId}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return response.data;
};

/**
 * Get conversation messages
 */
export const getConversationMessages = async (conversationId, limit = 100, offset = 0) => {
  const token = getAccessToken();
  const response = await api.get(`/api/conversations/${conversationId}/messages`, {
    params: { limit, offset },
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return response.data;
};

/**
 * Send message in conversation (AI reply saved on backend). Returns { user_message, assistant_message }.
 * Timeout 120s - AI response can take 30-60+ seconds (RAG + OpenAI).
 */
export const sendConversationMessage = async (conversationId, content, attachment = null, attachmentType = null) => {
  const token = getAccessToken();
  const data = new FormData();
  const safeContent = typeof content === "string" ? content : "";
  data.append("content", safeContent);
  data.append("message", safeContent);
  if (attachment) {
    data.append("attachment", attachment);
    if (attachmentType) data.append("attachment_type", attachmentType);
  }
  if (conversationId) data.append("conversation_id", String(conversationId));

  const response = await api.post(
    `/api/conversations/${conversationId}/messages`,
    data,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 120000,
    }
  );
  return response.data;
};

/**
 * Save prescription result (user + assistant messages, no AI call)
 */
export const savePrescriptionMessages = async (conversationId, userContent, assistantContent) => {
  const token = getAccessToken();
  const response = await api.post(
    `/api/conversations/${conversationId}/messages/prescription`,
    { user_content: userContent, assistant_content: assistantContent },
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 30000,
    }
  );
  return response.data;
};

/**
 * Update conversation (e.g. title)
 */
export const updateConversation = async (conversationId, { title }) => {
  const token = getAccessToken();
  const response = await api.patch(
    `/api/conversations/${conversationId}`,
    { title },
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  );
  return response.data;
};

/**
 * Delete (archive) conversation
 */
export const deleteConversation = async (conversationId) => {
  const token = getAccessToken();
  await api.delete(`/api/conversations/${conversationId}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return true;
};

/**
 * Extract text from prescription image via OCR (POST /api/extract-text)
 */
export const extractTextFromImage = async (file) => {
  const formData = new FormData();
  formData.append("file", file, file.name || "prescription.jpg");

  const token = getAccessToken();
  const config = {
    timeout: 60000,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  };
  const response = await api.post("/api/extract-text", formData, config);
  return response.data;
};

/**
 * Extract text from document (PDF, DOCX, DOC, TXT) - POST /api/extract-document
 */
export const extractTextFromDocument = async (file) => {
  const formData = new FormData();
  formData.append("file", file, file.name || "document.pdf");

  const token = getAccessToken();
  const config = {
    timeout: 60000,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  };
  const response = await api.post("/api/extract-document", formData, config);
  return response.data;
};

/**
 * Send voice message (audio file) - legacy /api/chat/voice
 */
export const sendVoiceMessage = async (audioBlob, userId = null, conversationId = null) => {
  const formData = new FormData();
  formData.append('audio', audioBlob, 'voice_message.webm');
  if (userId) formData.append('user_id', userId);
  if (conversationId) formData.append('conversation_id', conversationId);

  const token = getAccessToken();
  const response = await api.post("/api/chat/voice", formData, {
    headers: {
      "Content-Type": "multipart/form-data",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    timeout: 120000,
  });
  return response.data;
};

export default api;

