/* 智能对话页面 v3.0 — 现代AI对话风格 */

import { api } from '../api.js';
import { createEl, renderTopbar, showConfirm } from '../components.js';
import { renderMarkdown, escapeHtml, showToast } from '../utils.js';

const chatState = {
  convId: null,
  docId: '',
  messages: [],
  conversations: [],
  isStreaming: false,
  skipAutoRestore: false,
};

const ALL_KNOWLEDGE_VALUE = '__all__';

function selectedDocumentId() {
  const docSelect = document.getElementById('docSelect');
  const value = docSelect?.value || ALL_KNOWLEDGE_VALUE;
  if (value === ALL_KNOWLEDGE_VALUE) return null;
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function documentSelectValue(docId) {
  return docId ? String(docId) : ALL_KNOWLEDGE_VALUE;
}

const welcomeMarkup = `
  <div class="chat-welcome">
    <div class="chat-welcome-icon">✦</div>
    <h3>AI 学习助手</h3>
    <p>选择文档或直接提问，开始一段智能对话</p>
  </div>
`;

export function renderChatPage() {
  renderTopbar('chat');

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="chat-page">
      <div class="page-header">
        <h2>智能对话</h2>
      </div>

      <!-- 左侧栏 — 上下文控制 -->
      <div class="chat-sidebar">
        <div>
          <div class="sidebar-label">关联文档</div>
          <select id="docSelect">
            <option value="${ALL_KNOWLEDGE_VALUE}">通用知识库（全部资料）</option>
          </select>
        </div>
        <div>
          <div class="sidebar-label">模型</div>
          <div id="modelDisplay" class="sidebar-value">加载中...</div>
        </div>
        <button id="newChatBtn" class="btn btn-ghost">新对话</button>
        <div class="chat-sidebar-section">
          <div class="sidebar-label">历史对话</div>
          <div id="conversationList" class="conversation-list">
            <div class="conversation-empty">加载中...</div>
          </div>
        </div>
      </div>

      <!-- 主对话区 -->
      <div class="chat-main">
        <div id="chatHistory" class="chat-history">${welcomeMarkup}</div>
        <div class="chat-input-area">
          <textarea id="chatInput" placeholder="输入问题，Enter 发送，Shift+Enter 换行" rows="1"></textarea>
          <button id="sendBtn" class="btn btn-primary">发送</button>
        </div>
      </div>
    </div>
  `;

  let convId = chatState.convId;
  let isFirstMsg = chatState.messages.length === 0;
  let rawReplyText = '';  // 保存原始 Markdown 文本，避免 textContent 丢失 HTML
  const chatHistory = document.getElementById('chatHistory');
  const chatInput = document.getElementById('chatInput');

  renderStoredMessages();
  loadDocOptions().then(() => {
    const docSelect = document.getElementById('docSelect');
    if (docSelect) docSelect.value = documentSelectValue(chatState.docId);
  });
  loadModelDisplay();
  loadConversationList();
  restoreLatestConversation();

  document.getElementById('newChatBtn').addEventListener('click', () => {
    if (chatState.isStreaming) {
      showToast('当前回答还在生成，请稍后再新建对话', 'info');
      return;
    }
    convId = null;
    chatState.convId = null;
    chatState.docId = '';
    chatState.messages = [];
    chatState.isStreaming = false;
    chatState.skipAutoRestore = true;
    isFirstMsg = true;
    chatHistory.innerHTML = welcomeMarkup;
    const docSelect = document.getElementById('docSelect');
    if (docSelect) docSelect.value = ALL_KNOWLEDGE_VALUE;
    renderConversationList();
  });

  async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    const documentId = selectedDocumentId();
    chatState.docId = documentId ? String(documentId) : '';
    chatState.skipAutoRestore = false;

    if (isFirstMsg) { chatHistory.innerHTML = ''; isFirstMsg = false; }

    addMessage('user', message);
    chatState.messages.push({ role: 'user', content: message });
    chatInput.value = '';
    chatInput.style.height = 'auto';

    if (!convId) {
      const r = await api.post('/conversations', { title: message.slice(0, 30), document_id: documentId });
      if (r && r.id) {
        convId = r.id;
        chatState.convId = r.id;
        await loadConversationList(convId);
      }
    }

    const aiMsg = addMessage('assistant', '', true);
    const textEl = aiMsg.querySelector('.msg-text');
    rawReplyText = '';
    const assistantMessage = { role: 'assistant', content: '', streaming: true };
    chatState.messages.push(assistantMessage);
    chatState.isStreaming = true;

    api.stream(
      `/conversations/${convId}/messages`,
      { message, document_id: documentId, stream: true },
      chunk => {
        rawReplyText += chunk;
        assistantMessage.content = rawReplyText;
        if (document.body.contains(textEl)) {
          textEl.innerHTML = renderMarkdown(rawReplyText);
          chatHistory.scrollTop = chatHistory.scrollHeight;
        } else {
          updateVisibleStreamingMessage(rawReplyText);
        }
      },
      data => {
        assistantMessage.streaming = false;
        chatState.isStreaming = false;
        if (!document.body.contains(aiMsg)) {
          clearVisibleTypingDots();
          return;
        }
        aiMsg.querySelector('.typing-dots')?.remove();
        const debugResults = data.retrieval_debug?.results || [];
        if ((data.sources && data.sources.length) || debugResults.length) {
          // 兼容旧格式：sources 可能是字符串数组（旧后端）或对象数组（新后端）
          const normalized = (debugResults.length ? debugResults : data.sources).map((src, idx) => {
            if (typeof src === 'string') {
              return { doc_name: '未知文档', score: 0, preview: src.slice(0, 120), content: src };
            }
            return src;
          });
          renderSourceCards(aiMsg.querySelector('.chat-bubble'), normalized, data.retrieval_debug);
        }
        loadConversationList(convId);
      },
      err => {
        assistantMessage.streaming = false;
        chatState.isStreaming = false;
        assistantMessage.content += `\n[Error: ${err.message}]`;
        if (!document.body.contains(aiMsg)) {
          clearVisibleTypingDots();
          return;
        }
        aiMsg.querySelector('.typing-dots')?.remove();
        textEl.textContent += `\n[错误: ${err.message}]`;
      }
    );
  }

  document.getElementById('sendBtn').addEventListener('click', sendMessage);
  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  });

  function renderStoredMessages() {
    if (!chatState.messages.length) return;
    chatHistory.innerHTML = '';
    chatState.messages.forEach(msg => addMessage(msg.role, msg.content, Boolean(msg.streaming)));
    isFirstMsg = false;
  }

  async function restoreLatestConversation() {
    if (chatState.skipAutoRestore || chatState.messages.length || chatState.isStreaming) return;
    try {
      const conversations = await loadConversationList();
      const latest = conversations.find(c => (c.message_count || 0) > 0) || conversations[0];
      if (!latest) return;

      const detail = await api.get(`/conversations/${latest.id}`);
      const messages = detail.messages || [];
      if (!messages.length) return;

      convId = latest.id;
      chatState.convId = latest.id;
      chatState.docId = latest.document_id ? String(latest.document_id) : '';
      chatState.messages = messages.map(m => ({ role: m.role, content: m.content || '' }));
      chatState.skipAutoRestore = false;
      renderStoredMessages();
      renderConversationList();

      const docSelect = document.getElementById('docSelect');
      if (docSelect) docSelect.value = documentSelectValue(chatState.docId);
    } catch (e) {
      // Keep the welcome state if restoring the conversation fails.
    }
  }

  async function loadConversationList(activeId = chatState.convId) {
    try {
      const data = await api.get('/conversations');
      chatState.conversations = data.conversations || [];
      renderConversationList(activeId);
      return chatState.conversations;
    } catch (e) {
      const listEl = document.getElementById('conversationList');
      if (listEl) listEl.innerHTML = '<div class="conversation-empty">历史加载失败</div>';
      return [];
    }
  }

  function renderConversationList(activeId = chatState.convId) {
    const listEl = document.getElementById('conversationList');
    if (!listEl) return;
    if (!chatState.conversations.length) {
      listEl.innerHTML = '<div class="conversation-empty">暂无历史对话</div>';
      return;
    }

    listEl.innerHTML = chatState.conversations.map(conv => {
      const title = escapeHtml(conv.title || '新对话');
      const activeClass = Number(conv.id) === Number(activeId) ? ' active' : '';
      const count = Number(conv.message_count || 0);
      const time = formatConversationTime(conv.updated_at || conv.created_at);
      return `
        <div class="conversation-item${activeClass}" data-conversation-id="${conv.id}">
          <button class="conversation-open" type="button" title="${title}">
            <span class="conversation-title">${title}</span>
            <span class="conversation-meta">${count} 条消息 · ${time}</span>
          </button>
          <button class="conversation-delete" type="button" title="删除对话" aria-label="删除对话" data-conversation-id="${conv.id}">×</button>
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.conversation-open').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.conversation-item');
        const id = Number(item?.dataset.conversationId);
        if (id) selectConversation(id);
      });
    });
    listEl.querySelectorAll('.conversation-delete').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const id = Number(btn.dataset.conversationId);
        if (id) deleteConversation(id);
      });
    });
  }

  async function selectConversation(id) {
    if (chatState.isStreaming) {
      showToast('当前回答还在生成，请稍后再切换对话', 'info');
      return;
    }
    const conversation = chatState.conversations.find(c => Number(c.id) === Number(id));
    try {
      const detail = await api.get(`/conversations/${id}`);
      const messages = detail.messages || [];
      convId = id;
      chatState.convId = id;
      const documentId = detail.conversation?.document_id || conversation?.document_id || '';
      chatState.docId = documentId ? String(documentId) : '';
      chatState.messages = messages.map(m => ({ role: m.role, content: m.content || '' }));
      chatState.skipAutoRestore = false;
      if (chatState.messages.length) {
        renderStoredMessages();
      } else {
        isFirstMsg = true;
        chatHistory.innerHTML = welcomeMarkup;
      }
      const docSelect = document.getElementById('docSelect');
      if (docSelect) docSelect.value = documentSelectValue(chatState.docId);
      renderConversationList(id);
    } catch (e) {
      showToast(`加载对话失败: ${e.message}`, 'error');
    }
  }

  async function deleteConversation(id) {
    if (chatState.isStreaming) {
      showToast('当前回答还在生成，请稍后再删除对话', 'info');
      return;
    }
    const ok = await showConfirm('删除后这段对话将无法恢复。确定删除？');
    if (!ok) return;
    try {
      await api.delete(`/conversations/${id}`);
      if (Number(chatState.convId) === Number(id)) {
        convId = null;
        chatState.convId = null;
        chatState.docId = '';
        chatState.messages = [];
        isFirstMsg = true;
        chatHistory.innerHTML = welcomeMarkup;
      }
      await loadConversationList(chatState.convId);
      showToast('对话已删除', 'success');
    } catch (e) {
      showToast(`删除失败: ${e.message}`, 'error');
    }
  }
}

function formatConversationTime(value) {
  if (!value) return '';
  const date = new Date(String(value).replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function updateVisibleStreamingMessage(content) {
  const history = document.getElementById('chatHistory');
  if (!history) return;
  const messages = history.querySelectorAll('.chat-message.chat-assistant .msg-text');
  const textEl = messages[messages.length - 1];
  if (!textEl) return;
  textEl.innerHTML = renderMarkdown(content);
  history.scrollTop = history.scrollHeight;
}

function clearVisibleTypingDots() {
  document.querySelector('#chatHistory .chat-message.chat-assistant:last-child .typing-dots')?.remove();
}

function addMessage(role, content, isStreaming = false) {
  const chatHistory = document.getElementById('chatHistory');
  const cls = role === 'user' ? 'chat-user' : 'chat-assistant';
  const div = createEl('div', { className: `chat-message ${cls}` });

  const avatarLetter = role === 'user' ? 'U' : 'AI';

  if (role === 'user') {
    if (isStreaming) {
      div.innerHTML = `
        <div class="chat-bubble"><span class="msg-text" style="white-space:pre-wrap"></span><div class="typing-dots"><span></span><span></span><span></span></div></div>
        <div class="chat-avatar">${avatarLetter}</div>
      `;
    } else {
      div.innerHTML = `
        <div class="chat-bubble"><span class="msg-text" style="white-space:pre-wrap">${escapeHtml(content)}</span></div>
        <div class="chat-avatar">${avatarLetter}</div>
      `;
    }
  } else {
    if (isStreaming) {
      div.innerHTML = `
        <div class="chat-avatar">${avatarLetter}</div>
        <div class="chat-bubble"><div class="msg-text"></div><div class="typing-dots"><span></span><span></span><span></span></div></div>
      `;
    } else {
      div.innerHTML = `
        <div class="chat-avatar">${avatarLetter}</div>
        <div class="chat-bubble"><div class="msg-text">${renderMarkdown(content)}</div></div>
      `;
    }
  }

  chatHistory.appendChild(div);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return div;
}

async function loadDocOptions() {
  try {
    const data = await api.get('/documents');
    if (data && data.documents) {
      const sel = document.getElementById('docSelect');
      data.documents.filter(d => d.status === 'parsed').forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = d.filename;
        sel.appendChild(opt);
      });
    }
  } catch (e) { /* ignore */ }
}

async function loadModelDisplay() {
  try {
    const data = await api.get('/models');
    const el = document.getElementById('modelDisplay');
    if (data && data.current && el) {
      el.textContent = data.current;
    }
  } catch (e) {
    const el = document.getElementById('modelDisplay');
    if (el) el.textContent = 'DeepSeek V4 Flash';
  }
}

/**
 * 渲染可展开的引用资料卡片
 */
function renderSourceCards(bubbleEl, sources, debug = null) {
  const container = document.createElement('div');
  container.className = 'chat-sources';

  // 标题栏（点击展开/收起）
  const header = document.createElement('div');
  header.className = 'source-header';
  const acceptedCount = debug?.accepted_count ?? sources.filter(src => src.accepted !== false).length;
  const threshold = debug?.score_threshold;
  const thresholdText = typeof threshold === 'number' ? `，阈值 ${Math.round(threshold * 100)}%` : '';
  header.innerHTML = `<span class="source-icon">📎</span> 检索上下文 ${acceptedCount}/${sources.length} 已注入${thresholdText} <span class="source-arrow">▸</span>`;
  header.addEventListener('click', () => {
    const list = container.querySelector('.source-list');
    const arrow = header.querySelector('.source-arrow');
    const isOpen = list.style.display !== 'none';
    list.style.display = isOpen ? 'none' : 'block';
    arrow.textContent = isOpen ? '▸' : '▾';
  });
  container.appendChild(header);

  // 卡片列表
  const list = document.createElement('div');
  list.className = 'source-list';
  list.style.display = 'none';

  sources.forEach((src, idx) => {
    const card = document.createElement('div');
    card.className = 'source-card';
    if (src.accepted === false) card.classList.add('source-card-muted');

    const scorePct = Math.round((src.score || 0) * 100);
    const docName = src.doc_name || '未知文档';
    const preview = src.preview || src.content?.slice(0, 120) || '';
    const rank = src.rank || idx + 1;
    const chunk = src.chunk_index ?? '-';
    const distance = typeof src.distance === 'number' ? src.distance.toFixed(4) : '-';
    const statusText = src.accepted === false ? '未注入' : '已注入';
    const statusClass = src.accepted === false ? 'source-status-muted' : 'source-status-ok';

    // 卡片头部：序号 + 文档名 + 相关度
    const meta = document.createElement('div');
    meta.className = 'source-meta';
    meta.innerHTML = `
      <span class="source-idx">${rank}</span>
      <span class="source-doc">${escapeHtml(docName)}</span>
      <span class="source-status ${statusClass}">${statusText}</span>
      <span class="source-score">score ${scorePct}%</span>
    `;
    card.appendChild(meta);

    const detail = document.createElement('div');
    detail.className = 'source-detail';
    detail.textContent = `chunk ${chunk} · distance ${distance} · ${src.char_count || src.content?.length || 0} 字${src.reason ? ` · ${src.reason}` : ''}`;
    card.appendChild(detail);

    // 预览内容
    const previewEl = document.createElement('div');
    previewEl.className = 'source-preview';
    previewEl.textContent = preview + (src.content && src.content.length > 120 ? '...' : '');
    card.appendChild(previewEl);

    // 完整内容（默认收起）
    if (src.content && src.content.length > 120) {
      const fullEl = document.createElement('div');
      fullEl.className = 'source-full';
      fullEl.textContent = src.content;
      fullEl.style.display = 'none';

      const toggle = document.createElement('div');
      toggle.className = 'source-toggle';
      toggle.textContent = '展开全文';
      toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const expanded = fullEl.style.display !== 'none';
        fullEl.style.display = expanded ? 'none' : 'block';
        toggle.textContent = expanded ? '展开全文' : '收起';
      });
      card.appendChild(toggle);
      card.appendChild(fullEl);
    }

    list.appendChild(card);
  });

  container.appendChild(list);
  bubbleEl.appendChild(container);
}
