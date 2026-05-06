/* AI 资讯追踪页面 v2.5 */

import { api } from '../api.js';
import { renderTopbar, showEmpty, showConfirm } from '../components.js';
import { renderMarkdown, showToast, escapeHtml } from '../utils.js';

let currentFilter = 'all';
let pollingTimer = null;

export function renderNewsPage() {
  renderTopbar('news');

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>AI 资讯追踪</h2>
      <p>抓取AI行业动态，AI自动摘要，纳入知识库联动问答与测评</p>
    </div>

    <!-- URL 导入 -->
    <div class="card card-accent">
      <div class="card-header">导入文章</div>
      <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
        <div class="form-group" style="flex:1;min-width:280px;margin-bottom:0">
          <label class="form-label">文章URL（支持多个，每行一个）</label>
          <textarea id="articleUrls" class="form-input" rows="2"
            placeholder="https://mp.weixin.qq.com/...&#10;https://jiqizhixin.com/..."></textarea>
        </div>
        <button id="importBtn" class="btn btn-primary" style="margin-bottom:0">
          <span id="importText">导入</span>
          <span id="importSpinner" class="spinner hidden"></span>
        </button>
      </div>
      <div id="importResult" class="hidden mt-2"></div>
    </div>

    <!-- 筛选 + 操作栏 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin:24px 0;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:8px;flex-wrap:wrap" id="filterBar">
        <button class="btn btn-sm filter-btn active" data-filter="all">全部</button>
        <button class="btn btn-sm filter-btn" data-filter="unread">未读</button>
        <button class="btn btn-sm filter-btn" data-filter="digest">综合报告</button>
        <button class="btn btn-sm filter-btn" data-filter="manual">手动导入</button>
        <button class="btn btn-sm filter-btn" data-filter="rss">RSS</button>
        <button class="btn btn-sm filter-btn" data-filter="zh">中文</button>
        <button class="btn btn-sm filter-btn" data-filter="en">英文</button>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="rssManageBtn" class="btn btn-sm btn-secondary">RSS源管理</button>
        <button id="fetchAllBtn" class="btn btn-sm btn-primary">抓取全部</button>
        <button id="digestDayBtn" class="btn btn-sm btn-ghost">日报</button>
        <button id="digestWeekBtn" class="btn btn-sm btn-ghost">周报</button>
      </div>
    </div>

    <!-- 抓取状态条 -->
    <div id="fetchStatusBar" class="hidden" style="padding:12px 16px;background:var(--ivory-deep);border:1px solid var(--border);margin-bottom:16px;border-left:3px solid var(--rust)">
      <span id="fetchStatusText"></span>
    </div>

    <!-- 流式生成面板 -->
    <div id="streamingPanel" class="consolidated-panel hidden">
      <div class="consolidated-header">
        <h3 id="streamingTitle">AI综合报告生成中...</h3>
        <button id="streamingCloseBtn" class="btn btn-sm btn-ghost hidden">关闭</button>
      </div>
      <div id="streamingContent" class="consolidated-content"></div>
    </div>

    <!-- 文章列表 -->
    <div id="newsList">
      <div class="loading-state"><span class="spinner"></span><p>加载中...</p></div>
    </div>

    <!-- 全屏阅读弹窗 -->
    <div id="fullscreenModal" class="fullscreen-modal hidden">
      <div class="fullscreen-modal-backdrop" id="fullscreenBackdrop"></div>
      <div class="fullscreen-modal-content">
        <div class="fullscreen-modal-header">
          <h3 id="fullscreenTitle"></h3>
          <button id="fullscreenCloseBtn" class="btn btn-sm">&times; 关闭</button>
        </div>
        <div id="fullscreenBody" class="fullscreen-modal-body"></div>
      </div>
    </div>

    <!-- 原文列表弹窗 -->
    <div id="sourcesModal" class="fullscreen-modal hidden">
      <div class="fullscreen-modal-backdrop" id="sourcesBackdrop"></div>
      <div class="fullscreen-modal-content" style="max-width:700px;max-height:80vh">
        <div class="fullscreen-modal-header">
          <h3>原文列表</h3>
          <button id="sourcesCloseBtn" class="btn btn-sm">&times; 关闭</button>
        </div>
        <div id="sourcesBody" class="fullscreen-modal-body"></div>
      </div>
    </div>

    <!-- RSS 源管理面板 -->
    <div id="rssPanel" class="hidden"></div>

    <!-- AI摘要面板 -->
    <div id="digestPanel" class="hidden"></div>
  `;

  // 事件绑定
  document.getElementById('importBtn').addEventListener('click', handleImport);
  document.getElementById('rssManageBtn').addEventListener('click', toggleRssPanel);
  document.getElementById('fetchAllBtn').addEventListener('click', handleFetchAll);
  document.getElementById('digestDayBtn').addEventListener('click', () => generateDigest(1));
  document.getElementById('digestWeekBtn').addEventListener('click', () => generateDigest(7));

  // 全屏弹窗关闭
  document.getElementById('streamingCloseBtn').addEventListener('click', closeStreamingPanel);
  document.getElementById('fullscreenCloseBtn').addEventListener('click', closeFullscreenModal);
  document.getElementById('fullscreenBackdrop').addEventListener('click', closeFullscreenModal);
  document.getElementById('sourcesCloseBtn').addEventListener('click', closeSourcesModal);
  document.getElementById('sourcesBackdrop').addEventListener('click', closeSourcesModal);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeFullscreenModal(); closeSourcesModal(); } });

  document.querySelectorAll('#filterBar .filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#filterBar .filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      loadArticles();
    });
  });

  loadArticles();
}

// ═══════════ 文章列表 ═══════════

async function loadArticles() {
  const el = document.getElementById('newsList');
  el.innerHTML = '<div class="loading-state"><span class="spinner"></span><p>加载中...</p></div>';

  const params = { page: 1, per_page: 50 };
  if (currentFilter === 'unread') params.is_read = 0;
  else if (currentFilter === 'rss') params.source_type = 'rss';
  else if (currentFilter === 'manual') params.source_type = 'manual';
  else if (currentFilter === 'digest') params.source_type = 'digest';
  else if (currentFilter === 'zh') params.language = 'zh';
  else if (currentFilter === 'en') params.language = 'en';
  // "全部" 默认不传 source_type（后端返回除 rss 外的所有）

  try {
    const data = await api.get('/news/articles', params);
    const articles = data.articles || [];
    const stats = data.stats || {};

    // 更新筛选按钮计数
    const allBtn = document.querySelector('[data-filter="all"]');
    if (allBtn) allBtn.textContent = `全部 (${stats.total || 0})`;
    const unreadBtn = document.querySelector('[data-filter="unread"]');
    if (unreadBtn) unreadBtn.textContent = `未读 (${stats.unread || 0})`;

    if (!articles.length) {
      el.innerHTML = showEmpty('', '还没有导入资讯文章，试试粘贴一篇文章URL或添加RSS源');
      return;
    }

    el.innerHTML = articles.map(a => {
      const keyPoints = safeJsonParse(a.key_points, []);
      const topics = safeJsonParse(a.topics, []);
      const langBadge = a.language === 'en' ? '<span class="news-badge news-badge-lang">EN</span>' : '';
      const isDigest = a.source_type === 'digest';
      const isRss = a.source_type === 'rss';

      let sourceBadge;
      if (isDigest) {
        sourceBadge = '<span class="news-badge news-badge-digest">综合报告</span>';
      } else if (isRss) {
        sourceBadge = `<span class="news-badge news-badge-source">${escapeHtml(a.source_name || 'RSS')}</span>`;
      } else {
        sourceBadge = '<span class="news-badge news-badge-manual">手动</span>';
      }

      const unreadClass = !a.is_read ? 'unread' : '';
      const inLibrary = !!a.document_id;

      // 综合报告显示 markdown 内容
      const hasContent = (a.content || '').length > 100;
      const contentHtml = isDigest && hasContent
        ? `<div class="news-article-body news-article-markdown">${renderMarkdown(a.content)}</div>`
        : (hasContent ? `<div class="news-article-body">${escapeHtml(a.content)}</div>` : '');

      return `
        <div class="news-item ${unreadClass}" data-id="${a.id}">
          <div class="news-item-main" onclick="document.getElementById('newsDetail_${a.id}').classList.toggle('hidden')">
            <div class="news-title">${escapeHtml(a.title)}</div>
            <div class="news-meta">
              ${sourceBadge} ${langBadge}
              <span>${formatTime(a.created_at)}</span>
              ${inLibrary ? '<span class="news-badge" style="background:var(--forest-dim);color:var(--forest-soft)">已存库</span>' : ''}
              ${a.summary && !isDigest ? '' : (isDigest ? '' : '<span class="text-secondary">(待AI摘要)</span>')}
            </div>
            ${a.summary && !isDigest ? `<div class="news-summary">${escapeHtml(a.summary)}</div>` : ''}
            ${topics.length ? `
              <div class="news-key-points">
                ${topics.map(t => `<span class="news-key-point">${escapeHtml(t)}</span>`).join('')}
              </div>` : ''}
          </div>
          <div class="news-item-actions">
            <button class="news-action-btn" onclick="event.stopPropagation();window.NewsActions.toggleRead(${a.id}, ${a.is_read ? 1 : 0})">${a.is_read ? '✓ 已读' : '○ 未读'}</button>
            <button class="news-action-btn" onclick="event.stopPropagation();window.NewsActions.toggleBookmark(${a.id})">${a.is_bookmarked ? '★ 取消收藏' : '☆ 收藏'}</button>
            ${!inLibrary ? `<button class="news-action-btn news-action-primary" onclick="event.stopPropagation();window.NewsActions.saveToLibrary(${a.id})" id="saveBtn_${a.id}">存至知识库</button>` : ''}
            <button class="news-action-btn news-action-danger" onclick="event.stopPropagation();window.NewsActions.deleteArticle(${a.id})">删除</button>
          </div>
        </div>
        <div id="newsDetail_${a.id}" class="news-detail-panel hidden">
          ${keyPoints.length ? `
            <div class="news-key-points" style="margin-bottom:12px">
              <strong>关键要点：</strong>
              ${keyPoints.map(p => `<span class="news-key-point">${escapeHtml(p)}</span>`).join('')}
            </div>` : ''}
          ${contentHtml}
          <div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap">
            ${isDigest ? `<button class="news-action-btn news-action-primary" onclick="event.stopPropagation();window.NewsActions.openFullscreen(${a.id})">全屏阅读</button>` : ''}
            ${isDigest ? `<button class="news-action-btn" onclick="event.stopPropagation();window.NewsActions.openSources()">查看原文列表</button>` : ''}
            ${a.url ? `<a href="${escapeHtml(a.url)}" target="_blank" class="news-action-btn">打开原文 →</a>` : ''}
            ${inLibrary
              ? `<button class="news-action-btn news-action-primary" onclick="sessionStorage.setItem('quizDoc','${a.document_id}');window.location.hash='#/quiz'">去测评</button>`
              : `<button class="news-action-btn news-action-primary" onclick="window.NewsActions.saveToLibrary(${a.id})" id="saveDetailBtn_${a.id}">转存到知识库</button>`}
          </div>
        </div>
      `;
    }).join('');

  } catch (e) {
    el.innerHTML = showEmpty('', `加载失败: ${e.message}`);
  }
}

// ═══════════ 导入 ═══════════

async function handleImport() {
  const urlsText = document.getElementById('articleUrls').value.trim();
  if (!urlsText) { showToast('请输入URL', 'error'); return; }

  const urls = urlsText.split('\n').filter(u => u.trim());
  const importText = document.getElementById('importText');
  const spinner = document.getElementById('importSpinner');
  importText.classList.add('hidden');
  spinner.classList.remove('hidden');

  try {
    if (urls.length === 1) {
      const result = await api.post('/news/articles', { url: urls[0].trim() });
      if (result.skipped) {
        showToast(`文章已存在: ${result.title}`, 'info');
      } else if (result.error) {
        showToast(`导入失败: ${result.error}`, 'error');
      } else {
        showToast(`导入成功: ${result.title}`, 'success');
      }
    } else {
      const result = await api.post('/news/articles/batch', { urls: urlsText });
      showToast(`已开始后台导入 ${result.total} 篇文章`, 'info');
      pollBatchStatus();
    }
    document.getElementById('articleUrls').value = '';
    loadArticles();
  } catch (e) {
    showToast(`导入失败: ${e.message}`, 'error');
  }
  importText.classList.remove('hidden');
  spinner.classList.add('hidden');
}

// ═══════════ 抓取全部 ═══════════

async function handleFetchAll() {
  try {
    const result = await api.post('/news/fetch-all');
    if (result.status === 'completed' && result.total_sources === 0) {
      showToast(result.message || '没有活跃的RSS源', 'info');
      return;
    }
    showToast(`已开始后台抓取 ${result.total_sources} 个RSS源`, 'info');
    startPolling();
  } catch (e) {
    showToast(`抓取失败: ${e.message}`, 'error');
  }
}

function startPolling() {
  const bar = document.getElementById('fetchStatusBar');
  bar.classList.remove('hidden');
  document.getElementById('fetchStatusText').innerHTML =
    '<span class="spinner" style="width:14px;height:14px;border-width:2px"></span> 正在抓取资讯...';

  if (pollingTimer) clearInterval(pollingTimer);
  pollingTimer = setInterval(async () => {
    try {
      const status = await api.get('/news/fetch-status');
      if (status.status === 'idle') {
        stopPolling('没有正在进行的任务');
      } else if (status.status === 'running') {
        document.getElementById('fetchStatusText').textContent =
          `抓取中... ${status.done}/${status.total} 源 | 当前: ${status.current_source || ''}`;
      } else if (status.status === 'completed') {
        const msg = [];
        if (status.imported) msg.push(`导入 ${status.imported} 篇`);
        if (status.skipped) msg.push(`跳过 ${status.skipped} 篇`);
        if (status.errors && status.errors.length) msg.push(`${status.errors.length} 个错误`);
        const hasAvailable = (status.imported || 0) > 0 || (status.skipped || 0) > 0;
        stopPolling(`抓取完成：${msg.join('，')}${hasAvailable ? '，正在生成综合报告...' : ''}`);
        showToast('抓取完成', 'success');
        loadArticles();
        if (hasAvailable) {
          startStreamingConsolidation();
        }
      }
    } catch (e) {
      stopPolling('状态查询失败');
    }
  }, 2000);
}

function stopPolling(msg) {
  clearInterval(pollingTimer);
  pollingTimer = null;
  const bar = document.getElementById('fetchStatusBar');
  if (msg) {
    document.getElementById('fetchStatusText').textContent = msg;
    setTimeout(() => bar.classList.add('hidden'), 5000);
  } else {
    bar.classList.add('hidden');
  }
}

async function pollBatchStatus() {
  let attempts = 0;
  const check = async () => {
    if (attempts > 30) return;
    attempts++;
    try {
      const status = await api.get('/news/fetch-status');
      if (status.status === 'completed') {
        showToast(`批量导入完成: ${status.imported || 0} 篇成功`, 'success');
        loadArticles();
        return;
      }
    } catch (e) { /* ignore */ }
    setTimeout(check, 2000);
  };
  setTimeout(check, 2000);
}

// ═══════════ RSS 源管理 ═══════════

async function toggleRssPanel() {
  const panel = document.getElementById('rssPanel');
  if (!panel.classList.contains('hidden')) {
    panel.classList.add('hidden');
    return;
  }
  await renderRssPanel();
  panel.classList.remove('hidden');
  panel.scrollIntoView({ behavior: 'smooth' });
}

async function renderRssPanel() {
  const panel = document.getElementById('rssPanel');
  try {
    const data = await api.get('/news/sources');
    const sources = data.sources || [];
    panel.innerHTML = `
      <div class="card card-accent">
        <div class="card-header">RSS 源管理</div>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:16px">
          <div class="form-group" style="margin-bottom:0">
            <label class="form-label">名称</label>
            <input id="newRssName" class="form-input" placeholder="如: 机器之心">
          </div>
          <div class="form-group" style="flex:1;min-width:200px;margin-bottom:0">
            <label class="form-label">RSS URL</label>
            <input id="newRssUrl" class="form-input" placeholder="https://...rss">
          </div>
          <div class="form-group" style="margin-bottom:0">
            <label class="form-label">语言</label>
            <select id="newRssLang" class="form-select">
              <option value="zh">中文</option>
              <option value="en">英文</option>
            </select>
          </div>
          <button id="addRssBtn" class="btn btn-primary btn-sm">添加</button>
        </div>
        <div id="rssSourceList">
          ${sources.length ? sources.map(s => `
            <div class="rss-source-item" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)">
              <div>
                <span style="font-weight:600">${escapeHtml(s.name)}</span>
                <span class="news-badge" style="margin-left:8px">${s.language === 'en' ? 'EN' : '中文'}</span>
                <span style="margin-left:8px;font-size:0.72rem;color:var(--ink-muted)">${escapeHtml(s.url)}</span>
                <span style="margin-left:8px;font-size:0.7rem;color:var(--ink-soft)">${s.article_count || 0}篇 | ${s.is_active ? '活跃' : '已停用'}
                  ${s.last_fetched_at ? ' | 上次: ' + formatTime(s.last_fetched_at) : ''}
                </span>
              </div>
              <div style="display:flex;gap:6px">
                <button class="btn btn-sm btn-ghost" onclick="window.NewsActions.toggleSource(${s.id}, ${s.is_active ? 0 : 1})">${s.is_active ? '停用' : '启用'}</button>
                <button class="btn btn-sm btn-ghost" onclick="window.NewsActions.fetchSource(${s.id})">抓取</button>
                <button class="btn btn-sm btn-ghost danger" onclick="window.NewsActions.deleteSource(${s.id})">删除</button>
              </div>
            </div>
          `).join('') : '<p class="text-secondary">暂无RSS源</p>'}
        </div>
      </div>
    `;
    document.getElementById('addRssBtn').addEventListener('click', addRssSource);
  } catch (e) {
    showToast(`加载RSS源失败: ${e.message}`, 'error');
  }
}

async function addRssSource() {
  const name = document.getElementById('newRssName').value.trim();
  const url = document.getElementById('newRssUrl').value.trim();
  const language = document.getElementById('newRssLang').value;
  if (!name || !url) { showToast('名称和URL不能为空', 'error'); return; }
  try {
    await api.post('/news/sources', { name, url, language });
    showToast('RSS源已添加', 'success');
    renderRssPanel();
  } catch (e) {
    showToast(`添加失败: ${e.message}`, 'error');
  }
}

// ═══════════ AI摘要/日报 ═══════════

async function generateDigest(days) {
  const panel = document.getElementById('digestPanel');
  panel.classList.remove('hidden');
  panel.innerHTML = '<div class="card card-accent"><div class="card-header">' + (days === 1 ? '今日AI资讯日报' : '本周AI资讯周报') + '</div><div class="loading-state"><span class="spinner"></span><p>AI正在生成摘要...</p></div></div>';
  panel.scrollIntoView({ behavior: 'smooth' });

  try {
    const data = await api.post('/news/digest', { days });
    panel.innerHTML = `
      <div class="card card-accent">
        <div class="card-header">${days === 1 ? '今日AI资讯日报' : '本周AI资讯周报'}</div>
        <div class="report-content">${renderMarkdown(data.digest || '')}</div>
      </div>
    `;
  } catch (e) {
    panel.innerHTML = `<div class="card card-accent"><div class="card-header">生成失败</div><p class="text-secondary">${e.message}</p></div>`;
  }
}

// ═══════════ 综合报告流式生成 ═══════════

let streamingAbortController = null;

function startStreamingConsolidation() {
  const panel = document.getElementById('streamingPanel');
  const contentEl = document.getElementById('streamingContent');
  panel.classList.remove('hidden');

  const today = new Date().toISOString().slice(0, 10);
  document.getElementById('streamingTitle').textContent = `AI资讯综合报告 ${today}`;

  contentEl.innerHTML = '<div class="loading-state"><span class="spinner"></span><p>AI正在生成综合报告...</p></div>';
  panel.scrollIntoView({ behavior: 'smooth' });

  let accumulated = '';

  streamingAbortController = api.stream('/news/consolidate-stream', { days: 1 },
    chunk => {
      accumulated += chunk;
      contentEl.innerHTML = renderMarkdown(accumulated);
      contentEl.scrollTop = contentEl.scrollHeight;
    },
    data => {
      showToast('综合报告生成完成', 'success');
      document.getElementById('streamingTitle').textContent = data.title || '报告生成完成';
      document.getElementById('streamingCloseBtn').classList.remove('hidden');
      // 存储 article_id，供关闭时确认
      if (data.article_id) {
        panel.dataset.articleId = data.article_id;
      }
    },
    err => {
      contentEl.innerHTML = `<p style="color:var(--rust)">生成失败: ${err.message}</p>`;
      showToast(`生成失败: ${err.message}`, 'error');
    }
  );
}

function closeStreamingPanel() {
  const panel = document.getElementById('streamingPanel');
  const closeBtn = document.getElementById('streamingCloseBtn');
  panel.classList.add('hidden');
  closeBtn.classList.add('hidden');
  // 重置标题
  document.getElementById('streamingTitle').textContent = 'AI综合报告生成中...';
  loadArticles();
}

let currentFullscreenArticleId = null;

function openFullscreenModal(articleId) {
  currentFullscreenArticleId = articleId;
  // 从 DOM 中取已渲染的内容
  const detailEl = document.getElementById(`newsDetail_${articleId}`);
  if (!detailEl) {
    showToast('找不到文章内容', 'error');
    return;
  }

  // 找到文章标题
  const itemEl = detailEl.closest('.news-item') || detailEl.parentElement;
  let title = '阅读';
  if (itemEl) {
    const titleEl = itemEl.querySelector('.news-title');
    if (titleEl) title = titleEl.textContent;
  }

  const modal = document.getElementById('fullscreenModal');
  document.getElementById('fullscreenTitle').textContent = title;

  // 提取正文内容（markdown 渲染后的部分）
  const bodyEl = detailEl.querySelector('.news-article-markdown');
  document.getElementById('fullscreenBody').innerHTML = bodyEl ? bodyEl.innerHTML : detailEl.innerHTML;

  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeFullscreenModal() {
  document.getElementById('fullscreenModal').classList.add('hidden');
  document.body.style.overflow = '';
  currentFullscreenArticleId = null;
}

// ═══════════ 原文列表弹窗 ═══════════

async function openSourcesModal() {
  const modal = document.getElementById('sourcesModal');
  const body = document.getElementById('sourcesBody');
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  body.innerHTML = '<div class="loading-state"><span class="spinner"></span><p>加载中...</p></div>';

  try {
    const data = await api.get('/news/articles', { per_page: 50, source_type: 'rss' });
    const articles = (data.articles || []).filter(a => !a.summary);
    if (!articles.length) {
      body.innerHTML = '<p class="text-secondary">暂未找到原文</p>';
      return;
    }
    body.innerHTML = articles.map(a => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <div style="font-weight:600;margin-bottom:4px">${escapeHtml(a.title)}</div>
        <div style="font-size:0.78rem;color:var(--ink-muted);margin-bottom:4px">
          ${escapeHtml(a.source_name || '')} · ${formatTime(a.created_at)}
        </div>
        <a href="${escapeHtml(a.url)}" target="_blank" style="font-size:0.78rem;color:var(--rust)">打开原文 →</a>
      </div>
    `).join('');
  } catch (e) {
    body.innerHTML = `<p class="text-secondary">加载失败: ${e.message}</p>`;
  }
}

function closeSourcesModal() {
  document.getElementById('sourcesModal').classList.add('hidden');
  document.body.style.overflow = '';
}

// ═══════════ 全局操作 ═══════════

window.NewsActions = {
  async toggleRead(id, current) {
    await api.post(`/news/articles/${id}/read`, { is_read: current ? 0 : 1 });
    loadArticles();
  },
  async toggleBookmark(id) {
    await api.post(`/news/articles/${id}/bookmark`);
    loadArticles();
  },
  async saveToLibrary(id) {
    const btn = document.getElementById(`saveBtn_${id}`);
    const detailBtn = document.getElementById(`saveDetailBtn_${id}`);
    if (btn) { btn.disabled = true; btn.textContent = '处理中...'; }
    if (detailBtn) { detailBtn.disabled = true; detailBtn.textContent = '处理中...'; }
    try {
      const result = await api.post(`/news/articles/${id}/save-to-library`);
      if (result.error) {
        showToast(result.error, 'error');
      } else {
        showToast(`已存入知识库，提取了 ${result.knowledge_points?.length || 0} 个知识点`, 'success');
        loadArticles();
      }
    } catch (e) {
      showToast(`转存失败: ${e.message}`, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '存至知识库'; }
    if (detailBtn) { detailBtn.disabled = false; detailBtn.textContent = '转存到知识库'; }
  },
  async deleteArticle(id) {
    const ok = await showConfirm('确定删除这篇文章？');
    if (!ok) return;
    try {
      await api.delete(`/news/articles/${id}`);
      showToast('已删除', 'success');
      document.getElementById('articleDetail')?.classList.add('hidden');
      loadArticles();
    } catch (e) {
      showToast(`删除失败: ${e.message}`, 'error');
    }
  },
  async toggleSource(id, active) {
    await api.put(`/news/sources/${id}`, { is_active: active });
    showToast(active ? '已启用' : '已停用', 'success');
    renderRssPanel();
  },
  async fetchSource(id) {
    await api.post(`/news/sources/${id}/fetch`);
    showToast('已开始后台抓取', 'info');
    startPolling();
  },
  async deleteSource(id) {
    const ok = await showConfirm('确定删除这个RSS源？');
    if (!ok) return;
    try {
      await api.delete(`/news/sources/${id}`);
      showToast('已删除', 'success');
      renderRssPanel();
    } catch (e) {
      showToast(`删除失败: ${e.message}`, 'error');
    }
  },
  openFullscreen: openFullscreenModal,
  openSources: openSourcesModal
};

// ═══════════ 工具函数 ═══════════

function formatTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  const now = new Date();
  const diff = now - d;
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
  if (diff < 604800000) return Math.floor(diff / 86400000) + '天前';
  return d.toISOString().slice(0, 10);
}

function safeJsonParse(str, fallback) {
  try { return JSON.parse(str); }
  catch (e) { return fallback; }
}
