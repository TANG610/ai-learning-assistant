/* 可复用 UI 组件 */

import { escapeHtml } from './utils.js';

export function createEl(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'className') el.className = v;
    else if (k === 'innerHTML') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v);
  }
  for (const child of children) {
    if (typeof child === 'string') el.appendChild(document.createTextNode(child));
    else if (child instanceof Node) el.appendChild(child);
  }
  return el;
}

export function renderTopbar(activeTab) {
  const tabs = [
    { id: 'chat', label: '对话' },
    { id: 'library', label: '资料库' },
    { id: 'quiz', label: '测评' },
    { id: 'progress', label: '进度' },
    { id: 'report', label: '报告' },
    { id: 'settings', label: '设置' }
  ];

  const user = JSON.parse(localStorage.getItem('user') || '{}');

  const topbar = document.getElementById('topbar');
  topbar.innerHTML = `
    <div class="topbar-brand" onclick="window.location.hash='#/chat'"><em>AI</em> 学习助手</div>
    <div class="topbar-nav">
      ${tabs.map(t => `
        <button class="topbar-tab ${t.id === activeTab ? 'active' : ''}"
                data-page="${t.id}">${t.label}</button>
      `).join('')}
    </div>
    <div class="topbar-user">
      <span>${escapeHtml(user.username || '')}</span>
      <button class="logout-btn" id="logoutBtn">退出</button>
    </div>
  `;

  topbar.querySelectorAll('.topbar-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      window.location.hash = `#/${btn.dataset.page}`;
    });
  });

  document.getElementById('logoutBtn').addEventListener('click', () => {
    import('./auth.js').then(m => m.logout());
  });
}

export function showConfirm(message) {
  return new Promise(resolve => {
    const overlay = createEl('div', { className: 'modal-overlay' });
    overlay.innerHTML = `
      <div class="modal">
        <p style="font-size:15px;margin-bottom:24px;color:var(--text-primary)">${escapeHtml(message)}</p>
        <div style="display:flex;gap:10px;justify-content:flex-end">
          <button class="btn btn-secondary" id="modalCancel">取消</button>
          <button class="btn btn-danger" id="modalConfirm">确认删除</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
    overlay.querySelector('#modalCancel').addEventListener('click', () => { overlay.remove(); resolve(false); });
    overlay.querySelector('#modalConfirm').addEventListener('click', () => { overlay.remove(); resolve(true); });
  });
}

export function showEmpty(icon, message) {
  return `
    <div class="empty-state">
      <div class="empty-icon">${icon}</div>
      <p>${message}</p>
    </div>
  `;
}
