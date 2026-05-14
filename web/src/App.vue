<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed, reactive } from 'vue'
import {
  NConfigProvider, NLayout, NLayoutContent, NInput, NButton,
  NEmpty, NIcon, NTag, NPopover, darkTheme,
  type GlobalTheme,
} from 'naive-ui'
import {
  SendOutline, ChatbubblesOutline, MoonOutline, SunnyOutline,
  CopyOutline, TrashOutline, CheckmarkOutline,
} from '@vicons/ionicons5'
import { marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import axios from 'axios'
import config from './config'
import 'highlight.js/styles/github-dark.css'

// ── Markdown 配置 ──

marked.use(markedHighlight({
  langPrefix: 'hljs language-',
  highlight(code: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch { /* fallthrough */ }
    }
    return hljs.highlightAuto(code).value
  },
}))

marked.setOptions({
  breaks: true,
  gfm: true,
})

// ── 类型 ──

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  error?: boolean
}

// ── 状态 ──

const messages = ref<Message[]>([])
const inputValue = ref('')
const loading = ref(false)
const sessionId = ref('')
const darkMode = ref(false)
const autoScroll = ref(true)
const copiedId = ref('')

const theme = computed<GlobalTheme | undefined>(() => (darkMode.value ? darkTheme : undefined))
const messageListRef = ref<HTMLElement | null>(null)
const inputRef = ref<InstanceType<typeof NInput> | null>(null)

// ── Markdown 渲染 ──

const renderedHtml = reactive<Record<string, string>>({})

async function renderMessageMarkdown(msg: Message) {
  if (msg.role !== 'assistant' || renderedHtml[msg.id]) return
  try {
    renderedHtml[msg.id] = await marked.parse(msg.content)
  } catch {
    renderedHtml[msg.id] = msg.content
  }
}

// 当消息列表变化时，自动渲染新的 markdown
watch(messages, () => {
  for (const msg of messages.value) {
    if (msg.role === 'assistant' && !renderedHtml[msg.id]) {
      renderMessageMarkdown(msg)
    }
  }
}, { deep: true, immediate: true })

// ── 自动滚动 ──

async function scrollToBottom(smooth = true) {
  await nextTick()
  if (!messageListRef.value) return
  messageListRef.value.scrollTo({
    top: messageListRef.value.scrollHeight,
    behavior: smooth ? 'smooth' : 'instant',
  })
}

watch(messages, () => {
  if (autoScroll.value) scrollToBottom()
}, { deep: true })

watch(loading, (v) => {
  if (v) scrollToBottom()
})

// ── 复制消息 ──

async function copyMessage(msg: Message) {
  try {
    await navigator.clipboard.writeText(msg.content)
    copiedId.value = msg.id
    setTimeout(() => { copiedId.value = '' }, 2000)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = msg.content
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copiedId.value = msg.id
    setTimeout(() => { copiedId.value = '' }, 2000)
  }
}

// ── 清空对话 ──

function clearConversation() {
  messages.value = []
  sessionId.value = ''
  inputValue.value = ''
  addWelcomeMessage()
  nextTick(() => inputRef.value?.focus())
}

// ── 发送消息 ──

async function chat() {
  const text = inputValue.value.trim()
  if (!text || loading.value) return

  const userMsg: Message = {
    id: Date.now().toString(),
    role: 'user',
    content: text,
    timestamp: new Date(),
  }
  messages.value.push(userMsg)
  inputValue.value = ''
  loading.value = true

  try {
    const response = await axios.post(`${config.API_BASE_URL}${config.API_PREFIX}/chat`, {
      message: text,
      user_id: 'web-user',
      session_id: sessionId.value || undefined,
    }, { timeout: 120000 })

    const data = response.data
    if (!sessionId.value && data.session_id) {
      sessionId.value = data.session_id
    }

    const assistantMsg: Message = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: data.response || '抱歉，我没有理解您的问题，请换个方式试试。',
      timestamp: new Date(),
    }
    messages.value.push(assistantMsg)
  } catch (error: any) {
    let errorText = '请求失败，请稍后重试'
    if (error.code === 'ECONNABORTED') {
      errorText = '请求超时，请检查网络连接后重试'
    } else if (error.response) {
      errorText = `服务器错误 (${error.response.status})，请联系管理员`
    } else if (error.request) {
      errorText = '无法连接到服务器，请检查后端服务是否启动'
    } else {
      errorText = error.message || '未知错误'
    }
    messages.value.push({
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: errorText,
      timestamp: new Date(),
      error: true,
    })
  } finally {
    loading.value = false
    nextTick(() => inputRef.value?.focus())
  }
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    chat()
  }
}

function addWelcomeMessage() {
  messages.value.push({
    id: '0',
    role: 'assistant',
    content: `您好！我是 **智能客服助手**，有什么可以帮您的吗？

您可以向我咨询以下内容：
- 📦 查询订单状态、物流信息
- ❓ 产品介绍、退款政策、开户流程
- 📋 创建工单、投诉建议
- 🔒 账户安全、合规问题`,
    timestamp: new Date(),
  })
}

// ── 生命周期 ──

onMounted(() => {
  addWelcomeMessage()
})

// ── 代码块复制 ──

function handleCodeBlockClick(e: Event) {
  const target = e.target as HTMLElement
  const copyBtn = target.closest('.code-copy-btn')
  if (!copyBtn) return

  const codeBlock = copyBtn.closest('.code-block-wrapper')
  if (!codeBlock) return
  const code = codeBlock.querySelector('code')?.textContent || ''

  navigator.clipboard.writeText(code).then(() => {
    copyBtn.textContent = '已复制!'
    setTimeout(() => { copyBtn.textContent = '复制' }, 2000)
  }).catch(() => {
    copyBtn.textContent = '复制失败'
  })
}
</script>

<template>
  <NConfigProvider :theme="theme" :theme-overrides="{
    common: {
      primaryColor: '#667eea',
      primaryColorHover: '#5a6fd6',
      primaryColorPressed: '#4e60c2',
    },
  }">
    <NLayout class="layout" :class="{ dark: darkMode }">
      <NLayoutContent class="content">
        <div class="chat-container">
          <!-- 顶部栏 -->
          <div class="chat-header">
            <div class="header-left">
              <ChatbubblesOutline :size="22" />
              <span class="header-title">智能客服系统</span>
              <NTag v-if="sessionId" size="tiny" round bordered>
                {{ sessionId.slice(0, 8) }}
              </NTag>
            </div>
            <div class="header-actions">
              <NPopover trigger="hover" placement="bottom">
                <template #trigger>
                  <NButton quaternary circle size="small" @click="clearConversation">
                    <template #icon><NIcon><TrashOutline /></NIcon></template>
                  </NButton>
                </template>
                <span>清空对话</span>
              </NPopover>
              <NPopover trigger="hover" placement="bottom">
                <template #trigger>
                  <NButton quaternary circle size="small" @click="darkMode = !darkMode">
                    <template #icon>
                      <NIcon><MoonOutline v-if="!darkMode" /><SunnyOutline v-else /></NIcon>
                    </template>
                  </NButton>
                </template>
                <span>{{ darkMode ? '浅色模式' : '深色模式' }}</span>
              </NPopover>
            </div>
          </div>

          <!-- 消息列表 -->
          <div class="messages" ref="messageListRef" @scroll.capture="handleCodeBlockClick">
            <div
              v-for="msg in messages"
              :key="msg.id"
              :class="['message', msg.role, { 'message-error': msg.error }]"
            >
              <div class="message-row">
                <!-- 头像 -->
                <div class="avatar" :class="msg.role">
                  <span v-if="msg.role === 'assistant'">AI</span>
                  <span v-else>我</span>
                </div>

                <!-- 内容区 -->
                <div class="message-body">
                  <div class="message-bubble" :class="{ error: msg.error }">
                    <div
                      v-if="msg.role === 'assistant'"
                      class="markdown-body"
                      v-html="renderedHtml[msg.id] || msg.content"
                    />
                    <div v-else class="user-text">{{ msg.content }}</div>
                  </div>

                  <!-- 操作按钮 -->
                  <div class="message-footer">
                    <div class="message-time">{{ new Date(msg.timestamp).toLocaleTimeString() }}</div>
                    <div class="message-actions">
                      <NPopover trigger="hover" placement="top">
                        <template #trigger>
                          <NButton
                            quaternary circle size="tiny"
                            @click="copyMessage(msg)"
                            class="action-btn"
                          >
                            <template #icon>
                              <NIcon :size="14">
                                <CheckmarkOutline v-if="copiedId === msg.id" />
                                <CopyOutline v-else />
                              </NIcon>
                            </template>
                          </NButton>
                        </template>
                        <span>{{ copiedId === msg.id ? '已复制' : '复制' }}</span>
                      </NPopover>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 加载状态 -->
            <div v-if="loading" class="message assistant">
              <div class="message-row">
                <div class="avatar assistant">AI</div>
                <div class="message-body">
                  <div class="message-bubble">
                    <div class="typing-indicator">
                      <span class="typing-dot"></span>
                      <span class="typing-dot"></span>
                      <span class="typing-dot"></span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="messages.length === 0 && !loading" class="empty-state">
              <NEmpty description="开始对话吧" />
            </div>
          </div>

          <!-- 输入区 -->
          <div class="input-area">
            <NInput
              ref="inputRef"
              v-model:value="inputValue"
              type="textarea"
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              :autosize="{ minRows: 1, maxRows: 4 }"
              @keydown="handleKeyDown"
              :disabled="loading"
              class="chat-input"
            />
            <NButton
              type="primary"
              :loading="loading"
              @click="chat"
              :disabled="!inputValue.trim()"
              class="send-btn"
              circle
            >
              <template #icon><NIcon :size="20"><SendOutline /></NIcon></template>
            </NButton>
          </div>

          <!-- 底部提示 -->
          <div class="footer-tip">
            智能客服，由 AI 驱动 · 回复仅供参考
          </div>
        </div>
      </NLayoutContent>
    </NLayout>
  </NConfigProvider>
</template>

<style>
/* ── 全局样式重置 ── */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --bg: #f0f2f5;
  --container-bg: #ffffff;
  --header-start: #667eea;
  --header-end: #764ba2;
  --user-bubble: #667eea;
  --user-text: #ffffff;
  --assistant-bubble: #f0f0f0;
  --assistant-text: #1a1a1a;
  --error-bg: #fef2f2;
  --error-text: #dc2626;
  --border: #e5e7eb;
  --text-secondary: #9ca3af;
  --footer-bg: #f9fafb;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  --radius: 12px;
}

/* ── Markdown 样式 ── */
.markdown-body pre {
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
  margin: 8px 0;
  position: relative;
}
.markdown-body code {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
}
.markdown-body p > code,
.markdown-body li > code {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.markdown-body p {
  margin: 6px 0;
  line-height: 1.6;
}
.markdown-body ul, .markdown-body ol {
  margin: 6px 0;
  padding-left: 20px;
}
.markdown-body li {
  margin: 3px 0;
  line-height: 1.6;
}
.markdown-body h1, .markdown-body h2, .markdown-body h3 {
  margin: 12px 0 6px;
}
.markdown-body blockquote {
  border-left: 3px solid #667eea;
  padding-left: 12px;
  color: #666;
  margin: 8px 0;
}
.markdown-body a {
  color: #667eea;
  text-decoration: none;
}
.markdown-body a:hover {
  text-decoration: underline;
}
.markdown-body table {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}
.markdown-body th, .markdown-body td {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}
.markdown-body th {
  background: #f5f5f5;
  font-weight: 600;
}

/* ── 代码块顶部栏 ── */
.code-block-wrapper {
  position: relative;
}
.code-block-wrapper::before {
  content: attr(data-lang);
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 6px 16px;
  font-size: 12px;
  color: #999;
  background: #2d2d2d;
  border-radius: 8px 8px 0 0;
  font-family: monospace;
}
.code-block-wrapper pre {
  padding-top: 36px !important;
}
.code-copy-btn {
  position: absolute;
  top: 4px;
  right: 8px;
  padding: 2px 8px;
  font-size: 11px;
  color: #999;
  background: transparent;
  border: 1px solid #444;
  border-radius: 4px;
  cursor: pointer;
  transition: all .2s;
}
.code-copy-btn:hover {
  color: #fff;
  border-color: #888;
}
</style>

<style scoped>
.layout {
  height: 100vh;
  background: var(--bg);
  transition: background .3s;
}
.layout.dark {
  --bg: #141414;
  --container-bg: #1f1f1f;
  --assistant-bubble: #2a2a2a;
  --assistant-text: #e0e0e0;
  --border: #333;
  --text-secondary: #666;
  --footer-bg: #1a1a1a;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

.content {
  display: flex;
  justify-content: center;
  height: 100vh;
}

.chat-container {
  width: 100%;
  max-width: 860px;
  height: 100vh;
  background: var(--container-bg);
  display: flex;
  flex-direction: column;
  box-shadow: -1px 0 0 var(--border), 1px 0 0 var(--border);
  transition: background .3s;
}

/* ── 顶部栏 ── */
.chat-header {
  padding: 14px 20px;
  background: linear-gradient(135deg, var(--header-start), var(--header-end));
  color: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-title {
  font-size: 17px;
  font-weight: 600;
}
.header-actions {
  display: flex;
  gap: 4px;
}
.header-actions :deep(.n-button) {
  color: rgba(255, 255, 255, 0.85);
}
.header-actions :deep(.n-button:hover) {
  color: #fff;
}

/* ── 消息列表 ── */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.messages::-webkit-scrollbar {
  width: 6px;
}
.messages::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
}
.messages::-webkit-scrollbar-track {
  background: transparent;
}

.message-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.message.user .message-row {
  flex-direction: row-reverse;
}

/* ── 头像 ── */
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: 0.5px;
}
.avatar.assistant {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
}
.avatar.user {
  background: #e8e8e8;
  color: #555;
}

/* ── 消息气泡 ── */
.message-body {
  max-width: 75%;
  min-width: 0;
}
.message-body :deep(.markdown-body) {
  /* 确保 markdown 样式在 scoped 中生效 */
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 14px;
  line-height: 1.5;
  font-size: 14px;
  word-break: break-word;
  position: relative;
  transition: background .3s, color .3s;
}
.message.assistant .message-bubble {
  background: var(--assistant-bubble);
  color: var(--assistant-text);
  border-top-left-radius: 4px;
}
.message.user .message-bubble {
  background: var(--user-bubble);
  color: var(--user-text);
  border-top-right-radius: 4px;
}
.message-bubble.error {
  background: var(--error-bg);
  color: var(--error-text);
  border: 1px solid rgba(220, 38, 38, 0.2);
}

.user-text {
  white-space: pre-wrap;
}

/* ── 消息底部 ── */
.message-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
  padding: 0 4px;
}
.message.user .message-footer {
  justify-content: flex-end;
}
.message-time {
  font-size: 11px;
  color: var(--text-secondary);
}
.message-actions {
  opacity: 0;
  transition: opacity .2s;
}
.message-body:hover .message-actions {
  opacity: 1;
}
.action-btn {
  color: var(--text-secondary) !important;
}

/* ── 空状态 ── */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── 输入区 ── */
.input-area {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 10px;
  align-items: flex-end;
  background: var(--container-bg);
  flex-shrink: 0;
  transition: background .3s, border-color .3s;
}
.chat-input {
  flex: 1;
}
.send-btn {
  margin-bottom: 2px;
}

/* ── 底部提示 ── */
.footer-tip {
  text-align: center;
  padding: 8px 20px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
  background: var(--footer-bg);
  flex-shrink: 0;
  transition: background .3s, border-color .3s, color .3s;
}

/* ── 打字动画 ── */
.typing-indicator {
  display: flex;
  gap: 5px;
  padding: 4px 0;
  align-items: center;
}
.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #999;
  animation: typingBounce 1.4s infinite ease-in-out both;
}
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
.typing-dot:nth-child(3) { animation-delay: 0s; }

@keyframes typingBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ── 响应式 ── */
@media (max-width: 640px) {
  .messages { padding: 12px; }
  .message-body { max-width: 85%; }
  .chat-header { padding: 12px 14px; }
  .header-title { font-size: 15px; }
  .input-area { padding: 10px 12px; }
  .message-bubble { font-size: 13px; padding: 8px 12px; }
}
</style>
