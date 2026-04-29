/* 用户设置页面 v2.3 — 模型提供商管理 */

import { api } from '../api.js';
import { renderTopbar, createEl } from '../components.js';
import { showToast, escapeHtml } from '../utils.js';

export async function renderSettingsPage() {
  renderTopbar('settings');

  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const content = document.getElementById('mainContent');

  let modelsData = null;
  let providersData = null;
  try { modelsData = await api.get('/models'); } catch (e) { /* */ }
  try { providersData = await api.get('/settings/providers'); } catch (e) { /* */ }

  const providers = providersData?.providers || [];

  content.innerHTML = `
    <div class="page-header">
      <h2>设置</h2>
      <p>用户偏好与模型配置</p>
    </div>

    <div class="settings-section">
      <h3>账户信息</h3>
      <div class="form-group">
        <label class="form-label">用户名</label>
        <input class="form-input" value="${escapeHtml(user.username || '')}" disabled>
      </div>
      <div class="form-group">
        <label class="form-label">邮箱</label>
        <input class="form-input" value="${escapeHtml(user.email || '')}" disabled>
      </div>
    </div>

    <div class="settings-section">
      <h3>模型选择</h3>
      <div class="form-group">
        <label class="form-label">当前模型</label>
        <select id="modelSelect" class="form-select">
          ${modelsData && modelsData.models ? modelsData.models.map(m =>
            `<option value="${m.id}" ${m.is_current ? 'selected' : ''}>${m.name} · ${m.type === 'multimodal' ? '全模态' : '文本'}</option>`
          ).join('') : '<option>DeepSeek V4 Flash</option>'}
        </select>
      </div>
      <button id="switchModelBtn" class="btn btn-primary btn-sm">切换模型</button>
    </div>

    <div class="settings-section">
      <div class="providers-header">
        <h3>模型提供商</h3>
        <button id="addProviderBtn" class="btn btn-primary btn-sm">+ 添加模型</button>
      </div>
      <p class="text-xs text-secondary" style="margin-bottom:16px">管理 API 提供商，配置后即时写入 .env 文件生效</p>

      <div id="providersList" class="providers-list">
        ${renderProvidersList(providers)}
      </div>
    </div>

    <div class="settings-section">
      <h3>系统信息</h3>
      <p class="text-sm text-secondary">AI 学习助手 v2.3 · 产品 PM 专版</p>
      <p class="text-sm text-secondary">Flask + ChromaDB + bge-small-zh-v1.5 (ONNX)</p>
      <p class="text-sm text-secondary">本地运行 · 数据安全</p>
    </div>
  `;

  // 模型切换
  document.getElementById('switchModelBtn').addEventListener('click', async () => {
    const model = document.getElementById('modelSelect').value;
    try {
      const res = await api.post('/models/switch', { model });
      if (res.status === 'switched') {
        showToast(`已切换至 ${model}`, 'success');
      }
    } catch (e) {
      showToast('切换失败，请确认 API Key 已配置', 'error');
    }
  });

  // 添加提供商
  document.getElementById('addProviderBtn').addEventListener('click', () => {
    showProviderModal(null, providers, async (updatedProviders) => {
      await saveProviders(updatedProviders);
    });
  });

  // 编辑/删除按钮
  document.getElementById('providersList').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const idx = parseInt(btn.dataset.index);
    if (isNaN(idx)) return;

    if (btn.classList.contains('edit-provider-btn')) {
      const p = providers[idx];
      showProviderModal(p, providers, async (updatedProviders) => {
        await saveProviders(updatedProviders);
      });
    } else if (btn.classList.contains('delete-provider-btn')) {
      providers.splice(idx, 1);
      saveProviders(providers);
    }
  });
}

function renderProvidersList(providers) {
  if (!providers.length) {
    return `<div class="empty-state" style="padding:32px"><p>暂无配置的模型提供商</p></div>`;
  }
  return providers.map((p, i) => `
    <div class="provider-card">
      <div class="provider-info">
        <div class="provider-name">${escapeHtml(p.name)}</div>
        <div class="provider-detail">
          <span class="badge ${p.type === 'multimodal' ? 'badge-info' : 'badge-success'}">${p.type === 'multimodal' ? '全模态' : '文本'}</span>
          <span class="text-xs text-secondary">${escapeHtml(p.model)} · ${escapeHtml(p.base_url)}</span>
        </div>
        <div class="provider-status">
          ${p.configured
            ? `<span class="text-xs" style="color:var(--forest)">已配置 · ${escapeHtml(p.masked)}</span>`
            : '<span class="text-xs" style="color:var(--ink-muted)">未配置 API Key</span>'}
        </div>
      </div>
      <div class="provider-actions">
        <button class="btn btn-ghost btn-sm edit-provider-btn" data-index="${i}">编辑</button>
        <button class="btn btn-danger btn-sm delete-provider-btn" data-index="${i}">删除</button>
      </div>
    </div>
  `).join('');
}

function showProviderModal(provider, allProviders, onSave) {
  const isEdit = provider !== null;
  const existingNames = allProviders.filter(p => p !== provider).map(p => p.name);

  const overlay = createEl('div', { className: 'modal-overlay' });
  overlay.innerHTML = `
    <div class="modal provider-modal">
      <div class="modal-title">${isEdit ? '编辑模型提供商' : '添加模型提供商'}</div>

      <div class="form-group">
        <label class="form-label">提供商名称</label>
        <input id="provName" class="form-input" value="${escapeHtml(isEdit ? provider.name : '')}" placeholder="例如：DeepSeek、OpenAI、智谱">
      </div>

      <div class="form-group">
        <label class="form-label">Base URL</label>
        <input id="provUrl" class="form-input" value="${escapeHtml(isEdit ? provider.base_url : '')}" placeholder="https://api.deepseek.com">
      </div>

      <div class="form-group">
        <label class="form-label">API Key</label>
        <div class="api-key-input-row">
          <input id="provKey" class="form-input" type="password" value="${escapeHtml(isEdit ? provider.api_key : '')}" placeholder="sk-...">
          <button type="button" class="btn btn-ghost btn-sm" id="toggleProvKey">显示</button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">模型名称</label>
        <input id="provModel" class="form-input" value="${escapeHtml(isEdit ? provider.model : '')}" placeholder="deepseek-v4-flash">
      </div>

      <div class="form-group">
        <label class="form-label">模型类型</label>
        <select id="provType" class="form-select">
          <option value="text" ${isEdit && provider.type === 'text' ? 'selected' : ''}>文本模型</option>
          <option value="multimodal" ${isEdit && provider.type === 'multimodal' ? 'selected' : ''}>全模态模型（支持图片）</option>
        </select>
      </div>

      <p id="provError" class="text-xs" style="color:var(--error);display:none;margin-bottom:12px"></p>

      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-secondary" id="provCancel">取消</button>
        <button class="btn btn-primary" id="provSave">保存</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const close = () => overlay.remove();

  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  overlay.querySelector('#provCancel').addEventListener('click', close);

  overlay.querySelector('#toggleProvKey').addEventListener('click', () => {
    const inp = overlay.querySelector('#provKey');
    const btn = overlay.querySelector('#toggleProvKey');
    const isPw = inp.type === 'password';
    inp.type = isPw ? 'text' : 'password';
    btn.textContent = isPw ? '隐藏' : '显示';
  });

  overlay.querySelector('#provSave').addEventListener('click', async () => {
    const name = overlay.querySelector('#provName').value.trim();
    const url = overlay.querySelector('#provUrl').value.trim();
    const key = overlay.querySelector('#provKey').value.trim();
    const model = overlay.querySelector('#provModel').value.trim();
    const type = overlay.querySelector('#provType').value;
    const errEl = overlay.querySelector('#provError');

    if (!name) { errEl.textContent = '请输入提供商名称'; errEl.style.display = 'block'; return; }
    if (!url) { errEl.textContent = '请输入 Base URL'; errEl.style.display = 'block'; return; }
    if (!key) { errEl.textContent = '请输入 API Key'; errEl.style.display = 'block'; return; }
    if (!model) { errEl.textContent = '请输入模型名称'; errEl.style.display = 'block'; return; }
    if (!isEdit && existingNames.includes(name)) { errEl.textContent = '该名称已存在'; errEl.style.display = 'block'; return; }

    const newProvider = { name, base_url: url, api_key: key, model, type };

    let updated;
    if (isEdit) {
      const idx = allProviders.indexOf(provider);
      updated = [...allProviders];
      updated[idx] = newProvider;
    } else {
      updated = [...allProviders, newProvider];
    }

    close();
    await onSave(updated);
  });
}

async function saveProviders(providers) {
  try {
    await api.post('/settings/providers', { providers });
    showToast('提供商配置已保存，即时生效', 'success');
    // 重新渲染当前页面
    await renderSettingsPage();
  } catch (e) {
    showToast('保存失败: ' + (e.message || '未知错误'), 'error');
  }
}
