/* 学习进度页面 v2.2 — 数据专题 */

import { api } from '../api.js';
import { renderTopbar, showEmpty } from '../components.js';
import { showToast } from '../utils.js';

const L = { 0: "未接触", 1: "入门", 2: "熟悉", 3: "精通", 4: "专家" };
const LC = { 0: "#9CA3AF", 1: "#F59E0B", 2: "#3B82F6", 3: "#22C55E", 4: "#8B5CF6" };

export async function renderProgressPage() {
  renderTopbar('progress');

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>学习进度</h2>
      <p>五级掌握度体系，追踪真实学习深度</p>
    </div>

    <div id="statsCards" class="metrics-grid">
      <div class="metric-card"><div class="metric-value">—</div></div>
      <div class="metric-card"><div class="metric-value">—</div></div>
      <div class="metric-card"><div class="metric-value">—</div></div>
      <div class="metric-card"><div class="metric-value">—</div></div>
    </div>

    <div class="progress-charts-row">
      <div>
        <h3 class="section-title">掌握度分布</h3>
        <div id="ringChart" class="chart-container" style="height:320px"></div>
      </div>
      <div>
        <h3 class="section-title">学习热力</h3>
        <div id="heatmapChart" class="chart-container" style="height:320px"></div>
      </div>
    </div>

    <div class="divider"></div>

    <h3 class="section-title">知识点掌握详情</h3>
    <div id="kpList"></div>

    <div class="divider"></div>

    <h3 class="section-title">档案学习进度</h3>
    <div id="docMasteryList"></div>

    <h3 class="section-title mt-4">需加强的知识点</h3>
    <div id="weakList"></div>
  `;

  await loadAllData();
}

async function loadAllData() {
  try {
    const [masteryData, calData] = await Promise.all([
      api.get('/progress/mastery'),
      api.get('/progress/calendar', { days: 90 })
    ]);

    if (masteryData) {
      renderStats(masteryData);
      renderRingChart(masteryData);
      renderKnowledgePoints(masteryData);
      renderDocMastery(masteryData);
      renderWeakPoints(masteryData);
    }
    if (calData && calData.calendar) {
      renderHeatmap(calData);
    }
  } catch (e) {
    document.getElementById('statsCards').innerHTML = `<p class="text-error">加载失败: ${e.message}</p>`;
  }
}

function renderStats(d) {
  document.getElementById('statsCards').innerHTML = `
    <div class="metric-card">
      <div class="metric-value">${d.total_docs || 0}</div>
      <div class="metric-label">学习资料</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${d.mastery_rate || 0}%</div>
      <div class="metric-label">知识掌握率</div>
      <div class="mini-bar"><div class="mini-bar-fill" style="width:${d.mastery_rate || 0}%"></div></div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${d.study_days || 0}</div>
      <div class="metric-label">学习天数</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${d.weak_count || 0}</div>
      <div class="metric-label">薄弱知识点</div>
    </div>
  `;
}

function renderRingChart(d) {
  const dom = document.getElementById('ringChart');
  if (!dom || typeof echarts === 'undefined') return;
  const chart = echarts.init(dom);

  const dist = d.level_distribution || {};
  const data = [0,1,2,3,4].map(lvl => ({
    value: dist[lvl] || 0,
    name: L[lvl],
    itemStyle: { color: d.level_colors?.[String(lvl)] || LC[lvl] }
  })).filter(x => x.value > 0);

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} 个知识点 ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['55%', '80%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      padAngle: 3,
      itemStyle: { borderRadius: 6, borderColor: '#FCF9F4', borderWidth: 3 },
      label: {
        show: true,
        position: 'outside',
        formatter: '{b}\n{d}%',
        fontSize: 11,
        color: '#5C5650',
        fontWeight: 600
      },
      emphasis: { scaleSize: 8 },
      labelLine: { length: 20, length2: 30, lineStyle: { color: '#C5BDB0' } },
      data: data.length > 0 ? data : [{ value: 1, name: '暂无数据', itemStyle: { color: '#E5DDD2' } }]
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

function renderHeatmap(calData) {
  const dom = document.getElementById('heatmapChart');
  if (!dom || typeof echarts === 'undefined') return;
  const chart = echarts.init(dom);

  const calendar = calData.calendar || [];
  const dateMap = {};
  calendar.forEach(c => { dateMap[c.date] = c.count; });

  const data = [];
  const now = new Date();
  const colors = ['#FCF9F4', '#F5E8D8', '#E8C9A0', '#D4A06A', '#B45428'];
  for (let i = 89; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const ds = d.toISOString().slice(0, 10);
    const count = dateMap[ds] || 0;
    data.push([ds, count]);
  }

  chart.setOption({
    tooltip: {
      formatter: p => `${p.value[0]}: ${p.value[1]} 次活动`
    },
    visualMap: {
      min: 0, max: Math.max(5, ...calendar.map(c => c.count)),
      orient: 'horizontal', left: 'center', bottom: 0,
      inRange: { color: colors },
      type: 'piecewise',
      pieces: [
        { min: 1, label: '有活动' },
        { value: 0, label: '无' }
      ]
    },
    calendar: {
      top: 20, left: 30, right: 20, bottom: 60,
      range: [new Date(now.getTime() - 89 * 86400000).toISOString().slice(0, 10), now.toISOString().slice(0, 10)],
      cellSize: [16, 16],
      splitLine: { lineStyle: { color: '#E5DDD2' } },
      itemStyle: { borderColor: '#F5EFE5', borderWidth: 2, borderRadius: 2 },
      yearLabel: { show: false },
      dayLabel: { fontSize: 10, color: '#9CA0A0' },
      monthLabel: { fontSize: 10, color: '#5C5650', fontWeight: 600 }
    },
    series: [{
      type: 'heatmap',
      coordinateSystem: 'calendar',
      data: data
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

function renderKnowledgePoints(d) {
  const kps = (d.knowledge_points || []).sort((a, b) => b.level - a.level);
  const el = document.getElementById('kpList');

  if (!kps.length) {
    el.innerHTML = '<p class="text-sm text-secondary">暂无知识点数据，完成测评后自动生成</p>';
    return;
  }

  el.innerHTML = kps.map(kp => `
    <div class="kp-item">
      <div class="kp-info">
        <span class="kp-name">${kp.topic}</span>
        <span class="kp-source text-xs text-secondary">${kp.source_file || ''}</span>
      </div>
      <span class="kp-level" style="color:${kp.level_color}">L${kp.level} ${kp.level_name}</span>
      <div class="kp-bar">
        <div class="kp-bar-fill" style="width:${kp.mastery_rate}%;background:${kp.level_color}"></div>
      </div>
      <span class="kp-rate">${kp.mastery_rate}%</span>
    </div>
  `).join('');
}

function renderDocMastery(d) {
  const docs = d.doc_mastery || [];
  const el = document.getElementById('docMasteryList');

  if (!docs.length) {
    el.innerHTML = '<p class="text-sm text-secondary">暂无学习档案</p>';
    return;
  }

  el.innerHTML = docs.map(doc => `
    <div class="expander">
      <div class="expander-header">
        <span class="doc-mastery-name">${doc.filename}</span>
        <span class="kp-level" style="color:${doc.level_color}">L${doc.level} ${doc.level_name}</span>
        <span class="expander-arrow">+</span>
      </div>
      <div class="expander-body">
        <div style="display:flex;gap:16px;flex-wrap:wrap">
          <span class="badge ${doc.best_score >= 80 ? 'badge-success' : doc.best_score >= 60 ? 'badge-warning' : 'badge-error'}">最佳 ${doc.best_score} 分</span>
          <span class="text-sm text-secondary">测评 ${doc.assess_count} 次</span>
          <span class="text-sm text-secondary">均分 ${doc.avg_score}</span>
          <span class="badge badge-info">${doc.status === 'completed' ? '已完成' : doc.status === 'in_progress' ? '学习中' : doc.status === 'review_needed' ? '需复习' : '未开始'}</span>
        </div>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('.expander-header').forEach(h => {
    h.addEventListener('click', () => h.parentElement.classList.toggle('open'));
  });
}

function renderWeakPoints(d) {
  const weak = d.weak_points || [];
  const el = document.getElementById('weakList');
  if (!weak.length) {
    el.innerHTML = '<p class="text-sm text-secondary">暂无薄弱知识点，继续保持！</p>';
    return;
  }
  el.innerHTML = `
    <ul class="weak-points-list">
      ${weak.map(p => `
        <li>
          <div>
            <strong>${p.topic || '未知'}</strong>
            <span class="kp-level" style="color:${p.level_color};margin-left:10px">L${p.level} ${p.level_name}</span>
          </div>
          <span class="text-sm text-secondary">正确率 ${p.mastery_rate}% · 来源：${p.source_file || '未知'}</span>
        </li>
      `).join('')}
    </ul>
  `;
}
