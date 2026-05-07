/* 智能对话页面 v3.0 — 现代AI对话风格 */

import { api } from '../api.js';
import { createEl, renderTopbar, showEmpty } from '../components.js';
import { renderMarkdown, escapeHtml, showToast } from '../utils.js';

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
            <option value="">通用问答</option>
          </select>
        </div>
        <div>
          <div class="sidebar-label">模型</div>
          <div id="modelDisplay" class="sidebar-value">加载中...</div>
        </div>
        <button id="newChatBtn" class="btn btn-ghost">新对话</button>
      </div>

      <!-- 主对话区 -->
      <div class="chat-main">
        <div id="chatHistory" class="chat-history">
          <div class="chat-welcome">
            <div class="chat-welcome-icon">✦</div>
            <h3>AI 学习助手</h3>
            <p>选择文档或直接提问，开始一段智能对话</p>
          </div>
        </div>
        <div class="chat-input-area">
          <textarea id="chatInput" placeholder="输入问题，Enter 发送，Shift+Enter 换行" rows="1"></textarea>
          <button id="sendBtn" class="btn btn-primary">发送</button>
        </div>
      </div>
    </div>
  `;

  let convId = null;
  let isFirstMsg = true;
  let rawReplyText = '';  // 保存原始 Markdown 文本，避免 textContent 丢失 HTML
  const chatHistory = document.getElementById('chatHistory');
  const chatInput = document.getElementById('chatInput');

  loadDocOptions();
  loadModelDisplay();

  document.getElementById('newChatBtn').addEventListener('click', () => {
    convId = null;
    isFirstMsg = true;
    chatHistory.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">✦</div>
        <h3>AI 学习助手</h3>
        <p>选择文档或直接提问，开始一段智能对话</p>
      </div>
    `;
  });

  async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    const docSelect = document.getElementById('docSelect');
    const docId = docSelect.value || null;

    if (isFirstMsg) { chatHistory.innerHTML = ''; isFirstMsg = false; }

    addMessage('user', message);
    chatInput.value = '';
    chatInput.style.height = 'auto';

    if (!convId) {
      const r = await api.post('/conversations', { title: message.slice(0, 30), document_id: docId ? parseInt(docId) : null });
      if (r && r.id) convId = r.id;
    }

    const aiMsg = addMessage('assistant', '', true);
    const textEl = aiMsg.querySelector('.msg-text');
    rawReplyText = '';

    api.stream(
      `/conversations/${convId}/messages`,
      { message, document_id: docId ? parseInt(docId) : null, stream: true },
      chunk => {
        rawReplyText += chunk;
        textEl.innerHTML = renderMarkdown(rawReplyText);
        chatHistory.scrollTop = chatHistory.scrollHeight;
      },
      data => {
        aiMsg.querySelector('.typing-dots')?.remove();
        if (data.sources && data.sources.length) {
          // 兼容旧格式：sources 可能是字符串数组（旧后端）或对象数组（新后端）
          const normalized = data.sources.map((src, idx) => {
            if (typeof src === 'string') {
              return { doc_name: '未知文档', score: 0, preview: src.slice(0, 120), content: src };
            }
            return src;
          });
          renderSourceCards(aiMsg.querySelector('.chat-bubble'), normalized);
        }
      },
      err => {
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
        <div class="chat-bubble"><span class="msg-text" style="white-space:pre-wrap"></span><div class="typing-dots"><span></span><span></span><span></span></div></div>
      `;
    } else {
      div.innerHTML = `
        <div class="chat-avatar">${avatarLetter}</div>
        <div class="chat-bubble"><span class="msg-text" style="white-space:pre-wrap">${escapeHtml(content)}</span></div>
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
function renderSourceCards(bubbleEl, sources) {
  const container = document.createElement('div');
  container.className = 'chat-sources';

  // 标题栏（点击展开/收起）
  const header = document.createElement('div');
  header.className = 'source-header';
  header.innerHTML = `<span class="source-icon">📎</span> 引用 ${sources.length} 个资料片段 <span class="source-arrow">▸</span>`;
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

    const scorePct = Math.round((src.score || 0) * 100);
    const docName = src.doc_name || '未知文档';
    const preview = src.preview || src.content?.slice(0, 120) || '';

    // 卡片头部：序号 + 文档名 + 相关度
    const meta = document.createElement('div');
    meta.className = 'source-meta';
    meta.innerHTML = `<span class="source-idx">${idx + 1}</span> <span class="source-doc">${escapeHtml(docName)}</span> <span class="source-score">相关度 ${scorePct}%</span>`;
    card.appendChild(meta);

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
