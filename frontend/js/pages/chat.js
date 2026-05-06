/* 智能对话页面 v2.2 — 访谈对开页 */

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
          ${showEmpty('', '选择文档或直接提问开始对话')}
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
  const chatHistory = document.getElementById('chatHistory');
  const chatInput = document.getElementById('chatInput');

  loadDocOptions();
  loadModelDisplay();

  document.getElementById('newChatBtn').addEventListener('click', () => {
    convId = null;
    isFirstMsg = true;
    chatHistory.innerHTML = showEmpty('', '开始新的对话');
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

    api.stream(
      `/conversations/${convId}/messages`,
      { message, document_id: docId ? parseInt(docId) : null, stream: true },
      chunk => {
        textEl.innerHTML = renderMarkdown(textEl.textContent + chunk);
        chatHistory.scrollTop = chatHistory.scrollHeight;
      },
      data => {
        aiMsg.querySelector('.typing-dots')?.remove();
        if (data.sources && data.sources.length) {
          const srcDiv = document.createElement('div');
          srcDiv.className = 'chat-sources';
          srcDiv.textContent = `引用 ${data.sources.length} 个资料片段`;
          aiMsg.appendChild(srcDiv);
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

  if (isStreaming) {
    div.innerHTML = '<span class="msg-text" style="white-space:pre-wrap"></span><div class="typing-dots"><span></span><span></span><span></span></div>';
  } else {
    div.innerHTML = `<span class="msg-text" style="white-space:pre-wrap">${escapeHtml(content)}</span>`;
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
