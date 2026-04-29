/* 用户设置页面 v2.2 — 版权页 */

import { api } from '../api.js';
import { renderTopbar } from '../components.js';
import { showToast, escapeHtml } from '../utils.js';

export async function renderSettingsPage() {
  renderTopbar('settings');

  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const content = document.getElementById('mainContent');

  let modelsData = null;
  let healthData = null;
  try { modelsData = await api.get('/models'); } catch (e) { /* */ }
  try { healthData = await api.get('/health'); } catch (e) { /* */ }

  content.innerHTML = `
    <div class="page-header">
      <h2>设置</h2>
      <p>用户偏好与 API 配置</p>
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
        <p class="text-xs text-secondary mt-1">切换后在对话页生效，刷新页面恢复默认</p>
      </div>
      <button id="switchModelBtn" class="btn btn-primary btn-sm">切换模型</button>
    </div>

    <div class="settings-section">
      <h3>API Key 状态</h3>
      <div class="api-key-row">
        <span class="api-key-label">DeepSeek V4 Flash</span>
        <span class="badge ${healthData && healthData.llm_configured ? 'badge-success' : 'badge-error'}">${healthData && healthData.llm_configured ? '已配置' : '未配置'}</span>
        <span class="text-xs text-secondary">LLM_API_KEY · 文本对话/出题/评判</span>
      </div>
      <div class="api-key-row">
        <span class="api-key-label">MiniMax 2.7</span>
        <span class="badge ${healthData && healthData.multimodal_configured ? 'badge-success' : 'badge-error'}">${healthData && healthData.multimodal_configured ? '已配置' : '未配置'}</span>
        <span class="text-xs text-secondary">MULTIMODAL_API_KEY · 图片理解/多模态解析</span>
      </div>
      <p class="text-xs text-secondary mt-2">在项目根目录的 .env 文件中配置 API Key，修改后需重启服务</p>
    </div>

    <div class="settings-section">
      <h3>系统信息</h3>
      <p class="text-sm text-secondary">AI 学习助手 v2.2 · 产品 PM 专版</p>
      <p class="text-sm text-secondary">Flask + ChromaDB + bge-small-zh-v1.5 (ONNX)</p>
      <p class="text-sm text-secondary">DeepSeek V4 Flash + MiniMax 2.7 双模型</p>
      <p class="text-sm text-secondary">本地运行 · 数据安全</p>
    </div>
  `;

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
}
