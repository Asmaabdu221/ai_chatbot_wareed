# ⚡ QUICK START - React Frontend

## 🚀 Get Started in 3 Minutes

### Step 1: Install Dependencies

Open terminal in the `frontend-react` folder:

```bash
cd c:\Users\asmaa\OneDrive\Desktop\ai_chatbot_wareed\frontend-react
npm install
```

This will take 1-2 minutes.

---

### Step 2: Configure Environment

Copy the example environment file:

```bash
copy .env.example .env
```

The default configuration connects to `http://localhost:8000` (your backend).

---

### Step 3: Start the App

```bash
npm start
```

The app will automatically open in your browser at `http://localhost:3000`

---

## ✅ What You'll See

### Left Sidebar:
- 🏥 Wareed logo
- "+ محادثة جديدة" button
- List of conversations
- Each conversation shows title and message count

### Right Main Window:
- Header with "المساعد الطبي" title
- Status indicator (green dot = connected)
- Welcome screen with 4 suggested questions
- Chat input at the bottom

---

## 💬 Try These Features

1. **Start Chatting:**
   - Click a suggested question, or
   - Type your own message
   - Press Enter or click the send button (↑)

2. **Create New Chat:**
   - Click "+ محادثة جديدة" in sidebar
   - Start a fresh conversation

3. **Switch Conversations:**
   - Click any conversation in the sidebar
   - Messages load instantly

4. **Delete Conversation:**
   - Hover over a conversation
   - Click the trash icon (🗑️)
   - Confirm deletion

---

## 🎨 Design Highlights

- **Clean & Professional:** No flashy colors, simple gray/white/blue
- **ChatGPT Style:** Similar layout and UX
- **Responsive:** Works on desktop, tablet, and mobile
- **Smooth Animations:** Professional feel
- **Arabic RTL:** Proper right-to-left layout

---

## 📊 Component Structure

```
App.js
├── ChatSidebar (left)
│   ├── New Chat Button
│   ├── Conversation List
│   └── Footer
└── ChatWindow (right)
    ├── Header
    ├── MessageList
    │   ├── Welcome Screen
    │   ├── Messages
    │   └── Typing Indicator
    └── ChatInput
```

---

## 🔧 Key Features

### Chat History Management
- ✅ Create unlimited conversations
- ✅ Auto-title based on first message
- ✅ Switch between conversations
- ✅ Delete unwanted chats
- ✅ Persistent during session

### Messaging
- ✅ Send text messages
- ✅ Multi-line support (Shift+Enter)
- ✅ Auto-resize input box
- ✅ Typing indicator
- ✅ Auto-scroll to latest
- ✅ Timestamps on messages

### Design
- ✅ User messages: Blue, right side
- ✅ AI messages: White, left side
- ✅ Avatars (👤 user, 🤖 AI)
- ✅ Rounded corners
- ✅ Subtle shadows
- ✅ Professional spacing

---

## 🧪 Test Scenarios

### Scenario 1: Basic Chat
1. Open app
2. Click "ما هي خدمات وريد الصحية؟"
3. Wait for AI response
4. Verify response appears on left in white bubble

### Scenario 2: Multi-Turn Conversation
1. Send: "ما هي خدمات وريد؟"
2. Wait for response
3. Send: "كم سعر تحليل فيتامين د؟"
4. Verify AI remembers context

### Scenario 3: Multiple Conversations
1. Create new chat
2. Send different question
3. Switch back to first chat
4. Verify messages preserved

### Scenario 4: Mobile Responsive
1. Resize browser window
2. Verify sidebar stacks on top
3. Verify messages still readable
4. Test on actual mobile device

---

## ⚙️ Configuration

### Change API URL

Edit `.env` file:
```env
REACT_APP_API_URL=http://your-api-url:port
```

Restart the app after changes.

### Change Colors

Edit component CSS files:
- `#3b82f6` - Primary blue (user messages)
- `#f9fafb` - Background gray
- `#ffffff` - White (AI messages)

---

## 🐛 Troubleshooting

### "npm: command not found"
**Solution:** Install Node.js from nodejs.org

### Port 3000 already in use
**Solution:**
```bash
set PORT=3001
npm start
```

### Backend not responding
**Solution:**
1. Check backend is running on port 8000
2. Visit: http://localhost:8000/docs
3. Verify API health

### CORS errors
**Solution:** Backend already has CORS configured for localhost:3000

### Messages not sending
**Solution:**
1. Open browser console (F12)
2. Check Network tab for failed requests
3. Verify backend logs for errors

---

## 📦 Build for Production

When ready to deploy:

```bash
npm run build
```

This creates optimized files in `build/` folder.

Deploy `build/` folder to:
- Netlify
- Vercel  
- AWS S3
- Any static hosting

---

## 🎯 Next Steps

### During Development:
1. ✅ Test all features
2. ✅ Check on different devices
3. ✅ Verify error handling
4. ✅ Test with various questions

### For Production:
1. Add user authentication (optional)
2. Implement persistent storage (Phase 5)
3. Add analytics
4. Set up monitoring
5. Configure CDN
6. Enable HTTPS

---

## 📱 Mobile / Network Testing (e.g. http://192.168.1.112:3000)

1. **تشغيل الخادم للشبكة المحلية:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   (استخدم `--host 0.0.0.0` بدلاً من `127.0.0.1` لقبول الاتصالات من الشبكة)

2. **تشغيل الواجهة:**
   ```bash
   npm start
   ```

3. **الدخول من نفس الجهاز أو من جهاز آخر:**
   ```
   http://192.168.1.112:3000
   ```
   (الواجهة تختار عنوان الـ API تلقائياً وفق عنوان الصفحة)

---

## 💡 Pro Tips

1. **Hot Reload:** Code changes auto-refresh the browser
2. **Console:** Check browser console for debugging
3. **Network Tab:** Monitor API calls in DevTools
4. **React DevTools:** Install for component inspection
5. **Performance:** Use Lighthouse for optimization

---

## ✅ Pre-Launch Checklist

- [ ] All messages display correctly
- [ ] Chat history works
- [ ] Delete function works
- [ ] Mobile responsive
- [ ] Error handling tested
- [ ] API integration working
- [ ] No console errors
- [ ] Production build created
- [ ] Tested on multiple browsers
- [ ] Performance optimized

---

## 🎉 You're Ready!

Your professional React chat interface is complete and ready to use.

**Enjoy your ChatGPT-style Wareed AI Assistant!** 🏥

---

**Need help?** Check the full README.md for detailed documentation.
