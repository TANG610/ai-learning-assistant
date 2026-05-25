/* 社交媒体内容采集页面 �?MediaCrawler 集成 v1.0 */



import { api } from '../api.js';

import { renderTopbar, showEmpty, showConfirm } from '../components.js';

import { showToast, escapeHtml } from '../utils.js';



let pollingTimer = null;

let currentTaskId = null;



/** 渲染四阶段采集进度条 */

function renderCollectProgress(progress) {

  if (!progress) return '<span class="spinner" style="width:14px;height:14px;display:inline-block;margin-right:8px"></span>处理中...';



  const stages = [

    { key: 'crawling', label: '采集', icon: '🕷' },

    { key: 'asr', label: 'ASR', icon: '🎤' },

    { key: 'llm_summary', label: '摘要', icon: '📝' },

    { key: 'vector_import', label: '入库', icon: '📚' },

  ];



  const currentIdx = progress.stage_index || 0;

  const total = progress.total_records || 0;

  const processed = progress.processed_records || 0;



  // 逐条计数（仅在导入阶段显示）

  const recordInfo = total > 0 && currentIdx >= 1

    ? `<span style="margin-left:8px;font-size:12px;color:var(--ink-muted)">(${processed}/${total})</span>`

    : '';



  // 阶段指示
  const stageHtml = stages.map((s, i) => {

    const isActive = i === currentIdx;

    const isDone = i < currentIdx;

    const cls = isDone ? 'collect-stage-done' : isActive ? 'collect-stage-active' : 'collect-stage-pending';

    return `<div class="collect-stage ${cls}">

      <div class="collect-stage-dot">${isDone ? '✓' : s.icon}</div>

      <div class="collect-stage-label">${s.label}</div>

    </div>`;

  }).join('');



  // 整体进度
  const pct = total > 0 && currentIdx >= 1

    ? Math.round(((currentIdx * 0.25) + (processed / total) * 0.25) * 100)

    : Math.round((currentIdx / 4) * 100);



  const currentTitle = progress.current_record_title || '';



  return `

    <div class="collect-progress">

      <div class="collect-stages-row">${stageHtml}</div>

      <div class="collect-progress-bar">

        <div class="collect-progress-fill" style="width:${pct}%"></div>

      </div>

      <div class="collect-progress-info">

        <span>${stages[currentIdx]?.label || ''}中...${recordInfo}</span>

        ${currentTitle ? `<span class="collect-progress-title">${escapeHtml(currentTitle)}</span>` : ''}

      </div>

    </div>

  `;

}



export function renderCollectPage() {

  renderTopbar('collect');



  const content = document.getElementById('mainContent');

  content.innerHTML = `

    <div class="page-header">

      <h2>内容采集中心</h2>

      <p>从抖音、小红书等平台采集AI产品经理相关的碎片化知识，自动摘要并纳入知识库</p>

    </div>



    <!-- 系统状�?-->

    <div id="serviceStatus" class="card card-accent" style="margin-bottom:16px">

      <div class="card-header">MediaCrawler 服务状态</div>

      <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">

        <span id="serviceStatusBadge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:12px;font-size:13px">

          <span class="spinner" style="width:14px;height:14px"></span> 检查中...

        </span>

        <span id="serviceUrl" style="color:var(--text-secondary);font-size:13px">http://localhost:8080</span>

        <span id="serviceStats" style="color:var(--text-secondary);font-size:13px"></span>

      </div>

    </div>



    <!-- 操作�?-->

    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px">

      <div style="display:flex;gap:8px;flex-wrap:wrap">

        <button id="addSourceBtn" class="btn btn-primary">+ 添加采集源</button>

        <button id="collectAllBtn" class="btn btn-secondary">一键采集全部</button>

        <button id="stopCrawlBtn" class="btn btn-danger-text hidden">暂停采集</button>

        <button id="refreshBtn" class="btn btn-ghost">刷新</button>

      </div>

    </div>



    <!-- 采集源列�?-->

    <div id="sourcesList">

      <div class="loading-state"><span class="spinner"></span><p>加载中...</p></div>

    </div>



    <!-- 采集进度�?-->

    <div id="taskStatusBar" class="hidden" style="padding:12px 16px;background:var(--ivory-deep);border:1px solid var(--border);margin-bottom:16px;border-left:3px solid var(--rust);display:flex;align-items:center;gap:10px">

      <span class="spinner" style="width:16px;height:16px"></span>

      <span id="taskStatusText"></span>

    </div>



    <!-- 添加/编辑采集源弹�?-->

    <div id="sourceModal" class="fullscreen-modal hidden">

      <div class="fullscreen-modal-backdrop" id="sourceModalBackdrop"></div>

      <div class="fullscreen-modal-content" style="max-width:560px;max-height:85vh">

        <div class="fullscreen-modal-header">

          <h3 id="sourceModalTitle">添加采集源</h3>

          <button id="sourceModalClose" class="btn btn-sm">&times; 关闭</button>

        </div>

        <div class="fullscreen-modal-body" id="sourceModalBody">

          <form id="sourceForm" style="display:flex;flex-direction:column;gap:14px">

            <input type="hidden" id="sourceEditId" value="">

            <div class="form-group">

              <label class="form-label">采集源名称 *</label>

              <input type="text" id="sourceName" class="form-input" placeholder="例如：AI产品经理面试经验">

            </div>

            <div class="form-group">

              <label class="form-label">平台 *</label>

              <select id="sourcePlatform" class="form-input">

                <option value="">请选择平台</option>

                <option value="xhs">小红书</option>

                <option value="douyin">抖音</option>

                <option value="kuaishou">快手</option>

                <option value="bilibili">B站</option>

                <option value="weibo">微博</option>

              </select>

            </div>

            <div class="form-group">

              <label class="form-label">采集模式 *</label>

              <select id="sourceCrawlerType" class="form-input">

                <option value="search">关键词搜索</option>

                <option value="creator">指定博主</option>

                <option value="detail">单条视频</option>

              </select>

            </div>

            <div class="form-group" id="keywordsGroup">

              <label class="form-label">搜索关键词 *（每行一个）</label>

              <textarea id="sourceKeywords" class="form-input" rows="3"

                placeholder="AI产品经理面试&#10;产品经理必备技能&#10;大模型应用落地&#10;AI产品拆解"></textarea>

            </div>

            <div class="form-group hidden" id="creatorIdsGroup">

              <label class="form-label">博主ID *（每行一个）</label>

              <textarea id="sourceCreatorIds" class="form-input" rows="2"

                placeholder="输入博主主页ID或分享链接"></textarea>

            </div>

            <div class="form-group">

              <label class="form-label">每次采集最大数量</label>

              <input type="number" id="sourceMaxResults" class="form-input" value="1" min="1" max="100">

            </div>

            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">

              <button type="button" id="sourceModalCancelBtn" class="btn btn-secondary">取消</button>

              <button type="submit" class="btn btn-primary">

                <span id="sourceSubmitText">保存</span>

                <span id="sourceSubmitSpinner" class="spinner hidden" style="width:14px;height:14px"></span>

              </button>

            </div>

          </form>

        </div>

      </div>

    </div>

  `;



  // 绑定事件

  bindEvents();

  // 加载数据

  loadServiceStatus();

  loadSources().then(() => restoreCollectTask());

}



function bindEvents() {

  document.getElementById('addSourceBtn').addEventListener('click', () => openSourceModal());

  document.getElementById('collectAllBtn').addEventListener('click', handleCollectAll);

  document.getElementById('stopCrawlBtn').addEventListener('click', () => handleStopCrawl(currentTaskId));

  document.getElementById('refreshBtn').addEventListener('click', () => {

    loadServiceStatus();

    loadSources();

  });



  // 弹窗关闭

  document.getElementById('sourceModalClose').addEventListener('click', closeSourceModal);

  document.getElementById('sourceModalBackdrop').addEventListener('click', closeSourceModal);

  document.getElementById('sourceModalCancelBtn').addEventListener('click', closeSourceModal);



  // 表单提交

  document.getElementById('sourceForm').addEventListener('submit', handleSourceSubmit);



  // 采集模式切换

  document.getElementById('sourceCrawlerType').addEventListener('change', toggleCrawlerTypeFields);



  document.addEventListener('keydown', (e) => {

    if (e.key === 'Escape') closeSourceModal();

  });

}



// ══════════�?服务状�?══════════�?

async function loadServiceStatus() {

  const badge = document.getElementById('serviceStatusBadge');

  const stats = document.getElementById('serviceStats');



  try {

    const data = await api.get('/collector/info');

    stats.textContent = `${data.total_sources || 0} 个采集源 | ${data.articles_collected?.total || 0} 篇已采集`;



    // 检查 MediaCrawler 连通性
    try {

      const svcStatus = await api.get('/collector/service/status');

      if (svcStatus.error) {

        badge.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#ef4444;display:inline-block"></span> 服务未运行';

        badge.style.background = '#fef2f2';

      } else {

        badge.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#22c55e;display:inline-block"></span> 服务正常';

        badge.style.background = '#f0fdf4';

      }

    } catch {

      badge.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#ef4444;display:inline-block"></span> 服务未运行';

      badge.style.background = '#fef2f2';

    }

  } catch (e) {

    badge.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;display:inline-block"></span> 状态未知';

    badge.style.background = '#fffbeb';

  }

}



// ══════════�?采集源列�?══════════�?

async function loadSources() {

  const list = document.getElementById('sourcesList');

  try {

    const data = await api.get('/collector/sources');

    const sources = data.sources || [];



    if (sources.length === 0) {

      list.innerHTML = showEmpty('📡', '还没有采集源，点击上方按钮添加第一个');

      return;

    }



    const platformLabels = {

      xhs: '小红书', xiaohongshu: '小红书',

      douyin: '抖音', dy: '抖音',

      kuaishou: '快手', bilibili: 'B站', weibo: '微博'

    };

    const platformColors = {

      xhs: '#ff2442', xiaohongshu: '#ff2442',

      douyin: '#111', dy: '#111',

      kuaishou: '#ff4906', bilibili: '#fb7299', weibo: '#e6162d'

    };



    list.innerHTML = sources.map(s => {

      const platformName = platformLabels[s.platform] || s.platform;

      const platColor = platformColors[s.platform] || '#666';

      const isActive = s.is_active ? 'active' : 'inactive';

      const typeLabel = s.crawler_type === 'search'

        ? `关键词: ${s.keywords || '(未设置)'}`

        : s.crawler_type === 'detail'

          ? `视频ID/链接: ${s.creator_ids || s.keywords || '(未设置)'}`

          : `博主ID: ${s.creator_ids || '(未设置)'}`;



      return `

        <div class="card source-card" data-id="${s.id}" style="margin-bottom:12px">

          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">

            <div style="flex:1;min-width:200px">

              <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">

                <span style="display:inline-block;padding:2px 8px;border-radius:8px;font-size:11px;color:#fff;background:${platColor}">${platformName}</span>

                <span style="display:inline-block;padding:2px 8px;border-radius:8px;font-size:11px;background:${s.is_active ? '#dcfce7' : '#f3f4f6'};color:${s.is_active ? '#16a34a' : '#9ca3af'}">${s.is_active ? '启用' : '停用'}</span>

                <strong>${escapeHtml(s.name)}</strong>

              </div>

              <div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px">

                ${escapeHtml(typeLabel)} | 每次最多 ${s.max_results} 条
              </div>

              <div style="font-size:12px;color:var(--text-tertiary)">

                上次导入 ${s.article_count || 0} 篇 |

                最后采集 ${s.last_fetched_at || '从未'}

              </div>

            </div>

            <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">

              <button class="btn btn-sm btn-primary start-crawl-btn" data-id="${s.id}">

                <span class="crawl-btn-text">开始采集</span>

                <span class="crawl-btn-spinner spinner hidden" style="width:12px;height:12px"></span>

              </button>

              <button class="btn btn-sm btn-ghost edit-source-btn" data-id="${s.id}">编辑</button>

              <button class="btn btn-sm btn-danger-text delete-source-btn" data-id="${s.id}">删除</button>

            </div>

          </div>

          <!-- 任务状�?-->

          <div class="task-status hidden" id="taskStatus-${s.id}" style="margin-top:8px"></div>

        </div>

      `;

    }).join('');



    // 绑定按钮事件

    list.querySelectorAll('.start-crawl-btn').forEach(btn => {

      btn.addEventListener('click', () => handleStartCrawl(parseInt(btn.dataset.id), btn));

    });

    list.querySelectorAll('.edit-source-btn').forEach(btn => {

      btn.addEventListener('click', () => openSourceModal(parseInt(btn.dataset.id)));

    });

    list.querySelectorAll('.delete-source-btn').forEach(btn => {

      btn.addEventListener('click', () => handleDeleteSource(parseInt(btn.dataset.id)));

    });

  } catch (e) {

    list.innerHTML = `<p class="text-error">加载失败: ${e.message}</p>`;

  }

}



// ══════════�?采集操作 ══════════�?

async function restoreCollectTask() {

  try {

    let taskId = currentTaskId;

    if (!taskId) {

      const data = await api.get('/collector/crawl/status');

      const running = (data.tasks || []).find(t => t.status === 'running');

      taskId = running?.task_id || null;

    }

    if (!taskId) return;



    const status = await api.get('/collector/crawl/status', { task_id: taskId });

    if (!status || !['running', 'pending'].includes(status.status)) return;



    currentTaskId = taskId;

    const sourceId = status.source_id || parseInt(taskId);

    const stopBtn = document.getElementById('stopCrawlBtn');

    const statusBar = document.getElementById('taskStatusBar');

    const taskText = document.getElementById('taskStatusText');

    const statusDiv = document.getElementById(`taskStatus-${sourceId}`);



    stopBtn?.classList.remove('hidden');

    statusBar?.classList.remove('hidden');

    if (taskText) taskText.textContent = '采集任务仍在运行...';

    if (statusDiv) {

      statusDiv.classList.remove('hidden');

      statusDiv.innerHTML = renderCollectProgress(status.progress || null);

    }



    pollTaskStatus(taskId, sourceId);

  } catch (e) {

    // Ignore restore errors; manual refresh/status polling can recover later.

  }

}



async function handleStartCrawl(sourceId, buttonEl) {

  const textEl = buttonEl.querySelector('.crawl-btn-text');

  const spinnerEl = buttonEl.querySelector('.crawl-btn-spinner');

  const statusDiv = document.getElementById(`taskStatus-${sourceId}`);



  textEl.textContent = '启动中...';

  spinnerEl.classList.remove('hidden');

  buttonEl.disabled = true;



  try {

    const result = await api.post('/collector/crawl/start', { source_id: sourceId, auto_import: true });

    if (result.error) {

      showToast('采集启动失败: ' + result.error, 'error');

      return;

    }



    textEl.textContent = '采集中...';

    currentTaskId = result.task_id;

    document.getElementById('stopCrawlBtn').classList.remove('hidden');

    showToast(`采集任务已启动 ${result.source_name || ''}`, 'success');



    // 显示进度条并轮询

    statusDiv.classList.remove('hidden');

    statusDiv.innerHTML = '<span class="spinner" style="width:14px;height:14px;display:inline-block;margin-right:8px"></span>MediaCrawler 正在采集数据，请稍候...';

    document.getElementById('taskStatusBar').classList.remove('hidden');

    document.getElementById('taskStatusText').textContent = '正在执行采集任务...';



    pollTaskStatus(result.task_id, sourceId);

  } catch (e) {

    showToast('采集请求失败: ' + e.message, 'error');

  } finally {

    textEl.textContent = '开始采集';

    spinnerEl.classList.add('hidden');

    buttonEl.disabled = false;

  }

}



function pollTaskStatus(taskId, sourceId) {

  if (pollingTimer) clearInterval(pollingTimer);



  pollingTimer = setInterval(async () => {

    try {

      const status = await api.get('/collector/crawl/status', { task_id: taskId });

      const taskStatusBar = document.getElementById('taskStatusBar');

      if (!taskStatusBar) return;

      const stopBtn = document.getElementById('stopCrawlBtn');

      const taskStatusText = document.getElementById('taskStatusText');

      const statusDiv = sourceId ? document.getElementById(`taskStatus-${sourceId}`) : null;



      if (status.status === 'completed') {

        clearInterval(pollingTimer);

        pollingTimer = null;

        currentTaskId = null;

        stopBtn?.classList.add('hidden');

        taskStatusBar.classList.add('hidden');



        const imported = status.imported || 0;

        const skipped = status.skipped || 0;

        const errors = status.errors || [];



        if (statusDiv) {

          statusDiv.innerHTML = `

            <div style="padding:8px 12px;background:#f0fdf4;border-radius:8px;font-size:13px">

              采集完成！导入 ${imported} 篇，跳过 ${skipped} 篇
              ${errors.length > 0 ? `<br><span style="color:#ef4444">错误: ${errors.slice(0,3).map(escapeHtml).join('; ')}</span>` : ''}

            </div>

          `;

        }

        showToast(`采集完成: 导入 ${imported} 篇`, 'success');

        loadSources();

        loadServiceStatus();

      } else if (status.status === 'error') {

        clearInterval(pollingTimer);

        pollingTimer = null;

        currentTaskId = null;

        stopBtn?.classList.add('hidden');

        taskStatusBar.classList.add('hidden');

        if (statusDiv) {

          statusDiv.innerHTML = `<div style="padding:8px 12px;background:#fef2f2;border-radius:8px;font-size:13px;color:#ef4444">采集失败: ${escapeHtml(status.error || '未知错误')}</div>`;

        }

      } else if (status.status === 'stopped') {

        clearInterval(pollingTimer);

        pollingTimer = null;

        currentTaskId = null;

        stopBtn?.classList.add('hidden');

        taskStatusBar.classList.add('hidden');

        if (statusDiv) {

          statusDiv.innerHTML = '<div style="padding:8px 12px;background:#fffbeb;border-radius:8px;font-size:13px;color:#a16207">采集已暂停</div>';

        }

      } else {

        // 渲染四阶段进度条

        const progress = status.progress || null;
        const stageLabels = {
          crawling: '采集',
          asr: 'ASR转录',
          llm_summary: 'LLM摘要',
          vector_import: '向量入库',
        };

        if (taskStatusText) {
          taskStatusText.textContent = progress
            ? `${stageLabels[progress.stage] || '处理'}中...`
            : '处理中...';
        }

        if (statusDiv) {
          statusDiv.innerHTML = renderCollectProgress(progress);
        }

      }

    } catch (e) {

      // 轮询出错不中断页面
    }

  }, 3000);

}



async function handleCollectAll() {

  if (!await showConfirm('确认采集所有启用的采集源？这可能需要几分钟时间。')) return;



  const statusBar = document.getElementById('taskStatusBar');

  statusBar.classList.remove('hidden');

  document.getElementById('taskStatusText').textContent = '正在启动全部采集任务...';



  try {

    const result = await api.post('/collector/crawl/collect-all');

    if (result.status === 'completed' && result.total === 0) {

      statusBar.classList.add('hidden');

      showToast('没有活跃的采集源', 'warning');

      return;

    }



    showToast(`已启动 ${result.total || 0} 个采集任务`, 'success');

    document.getElementById('taskStatusText').textContent =

      `已启动 ${result.total || 0} 个采集任务，正在后台执行...`;



    const tasks = result.tasks || [];

    if (tasks.length > 0) {

      currentTaskId = tasks[0].task_id;

      document.getElementById('stopCrawlBtn').classList.remove('hidden');

      pollTaskStatus(tasks[0].task_id, null);

    }

  } catch (e) {

    statusBar.classList.add('hidden');

    showToast('一键采集失败: ' + e.message, 'error');

  }

}



async function handleStopCrawl(taskId = null) {

  const stopBtn = document.getElementById('stopCrawlBtn');

  stopBtn.disabled = true;

  stopBtn.textContent = '暂停中...';



  try {

    await api.post('/collector/crawl/stop', { task_id: taskId });

    if (pollingTimer) {

      clearInterval(pollingTimer);

      pollingTimer = null;

    }

    currentTaskId = null;

    document.getElementById('taskStatusBar')?.classList.add('hidden');
    stopBtn.classList.add('hidden');

    showToast('采集已暂停', 'success');

    loadSources();

    loadServiceStatus();

  } catch (e) {

    showToast('暂停采集失败: ' + e.message, 'error');

  } finally {

    stopBtn.disabled = false;

    stopBtn.textContent = '暂停采集';

  }

}



// ══════════�?采集源弹�?══════════�?

async function openSourceModal(sourceId = null) {

  const modal = document.getElementById('sourceModal');

  const title = document.getElementById('sourceModalTitle');

  const editId = document.getElementById('sourceEditId');



  if (sourceId) {

    // 编辑模式

    try {

      const data = await api.get(`/collector/sources/${sourceId}`);

      const src = data.source;

      title.textContent = '编辑采集源';

      editId.value = src.id;

      document.getElementById('sourceName').value = src.name;

      document.getElementById('sourcePlatform').value = src.platform;

      document.getElementById('sourceCrawlerType').value = src.crawler_type;

      document.getElementById('sourceKeywords').value = src.keywords || '';

      document.getElementById('sourceCreatorIds').value = src.creator_ids || '';

      document.getElementById('sourceMaxResults').value = src.max_results || 1;

    } catch (e) {

      showToast('加载采集源失败: ' + e.message, 'error');

      return;

    }

  } else {

    // 新建模式

    title.textContent = '添加采集源';

    editId.value = '';

    document.getElementById('sourceName').value = '';

    document.getElementById('sourcePlatform').value = '';

    document.getElementById('sourceCrawlerType').value = 'search';

    document.getElementById('sourceKeywords').value = '';

    document.getElementById('sourceCreatorIds').value = '';

    document.getElementById('sourceMaxResults').value = '1';

  }



  toggleCrawlerTypeFields();

  modal.classList.remove('hidden');

}



function closeSourceModal() {

  document.getElementById('sourceModal').classList.add('hidden');

}



function toggleCrawlerTypeFields() {

  const type = document.getElementById('sourceCrawlerType').value;

  document.getElementById('keywordsGroup').classList.toggle('hidden', type !== 'search');

  document.getElementById('creatorIdsGroup').classList.toggle('hidden', !['creator', 'detail'].includes(type));

}



async function handleSourceSubmit(e) {

  e.preventDefault();



  const editId = document.getElementById('sourceEditId').value;

  const submitText = document.getElementById('sourceSubmitText');

  const submitSpinner = document.getElementById('sourceSubmitSpinner');



  const body = {

    name: document.getElementById('sourceName').value.trim(),

    platform: document.getElementById('sourcePlatform').value,

    crawler_type: document.getElementById('sourceCrawlerType').value,

    keywords: document.getElementById('sourceKeywords').value.trim(),

    creator_ids: document.getElementById('sourceCreatorIds').value.trim(),

    max_results: parseInt(document.getElementById('sourceMaxResults').value) || 1,

  };



  // 前端校验

  if (!body.name) { showToast('请输入采集源名称', 'error'); return; }

  if (!body.platform) { showToast('请选择平台', 'error'); return; }

  if (body.crawler_type === 'search' && !body.keywords) {

    showToast('请输入搜索关键词', 'error'); return;

  }

  if (body.crawler_type === 'creator' && !body.creator_ids) {

    showToast('请输入博主ID', 'error'); return;

  }

  if (body.crawler_type === 'detail' && !body.creator_ids && !body.keywords) {

    showToast('请输入视频链接或视频ID', 'error'); return;

  }



  submitText.textContent = '保存中...';

  submitSpinner.classList.remove('hidden');



  try {

    if (editId) {

      await api.put(`/collector/sources/${editId}`, body);

      showToast('采集源已更新', 'success');

    } else {

      await api.post('/collector/sources', body);

      showToast('采集源已创建', 'success');

    }

    closeSourceModal();

    loadSources();

    loadServiceStatus();

  } catch (e) {

    showToast('保存失败: ' + e.message, 'error');

  } finally {

    submitText.textContent = '保存';

    submitSpinner.classList.add('hidden');

  }

}



async function handleDeleteSource(sourceId) {

  if (!await showConfirm('确认删除此采集源？相关的已采集文章不会受影响。')) return;



  try {

    await api.delete(`/collector/sources/${sourceId}`);

    showToast('采集源已删除', 'success');

    loadSources();

    loadServiceStatus();

  } catch (e) {

    showToast('删除失败: ' + e.message, 'error');

  }

}
