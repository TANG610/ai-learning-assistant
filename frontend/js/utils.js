/* 工具函数 */

export function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

export function formatDateTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr.slice(0, 16);
  return d.toLocaleString('zh-CN');
}

export function debounce(fn, delay = 300) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

export function showToast(message, type = 'info') {
  const icons = { success: '', error: '', info: '' };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(60px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

export function renderMarkdown(text) {
  if (!text) return '';
  if (typeof marked !== 'undefined') {
    try {
      marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
      });
      return marked.parse(text);
    } catch (e) {
      // fallback below
    }
  }
  // Fallback: basic manual rendering
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/\n/g, '<br>');
}

export function escapeHtml(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(str).replace(/[&<>"']/g, c => map[c]);
}

export function getProgressLabel(status) {
  const map = { not_started: '未开始', in_progress: '学习中', completed: '已完成', review_needed: '需复习' };
  return map[status] || status;
}

export function getStatusBadge(status) {
  const map = {
    parsed: ['success', '已解析'],
    uploaded: ['warning', '待处理'],
    error: ['error', '解析失败'],
    processing: ['info', '处理中']
  };
  const [cls, label] = map[status] || ['info', status];
  return `<span class="badge badge-${cls}">${label}</span>`;
}
