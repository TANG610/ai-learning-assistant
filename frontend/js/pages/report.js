/* 学习报告页面 v2.2 — 专题文章 */

import { api } from '../api.js';
import { renderTopbar, showEmpty } from '../components.js';
import { renderMarkdown, showToast } from '../utils.js';

export function renderReportPage() {
  renderTopbar('report');

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>学习报告</h2>
      <p>AI 基于你的学习数据自动生成周分析</p>
    </div>

    <div class="card card-accent">
      <div class="card-header">生成新报告</div>
      <div style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap">
        <div class="form-group" style="min-width:160px">
          <label class="form-label">报告类型</label>
          <select id="reportType" class="form-select">
            <option value="weekly">本周报告</option>
            <option value="custom">自定义时间</option>
          </select>
        </div>
        <div id="customRange" class="hidden" style="display:flex;gap:12px">
          <div><label class="form-label">开始</label><input id="weekStart" class="form-input" type="date"></div>
          <div><label class="form-label">结束</label><input id="weekEnd" class="form-input" type="date"></div>
        </div>
        <div style="padding-bottom:20px">
          <button id="generateBtn" class="btn btn-primary">
            <span id="genBtnText">生成报告</span>
            <span id="genSpinner" class="spinner hidden"></span>
          </button>
        </div>
      </div>
      <div id="reportResult" class="mt-3"></div>
    </div>

    <div class="divider"></div>
    <h3 class="section-title">历史报告</h3>
    <div id="reportHistory">
      <div class="loading-state"><span class="spinner"></span><p>加载中...</p></div>
    </div>
  `;

  document.getElementById('reportType').addEventListener('change', e => {
    const isCustom = e.target.value === 'custom';
    document.getElementById('customRange').classList.toggle('hidden', !isCustom);
    if (isCustom) document.getElementById('customRange').style.display = 'flex';
  });

  document.getElementById('generateBtn').addEventListener('click', generateReport);
  loadHistory();
}

async function generateReport() {
  const type = document.getElementById('reportType').value;
  const genBtn = document.getElementById('genBtnText');
  const spinner = document.getElementById('genSpinner');
  genBtn.classList.add('hidden');
  spinner.classList.remove('hidden');

  let body = {};
  if (type === 'custom') {
    body.week_start = document.getElementById('weekStart').value;
    body.week_end = document.getElementById('weekEnd').value;
    if (!body.week_start || !body.week_end) {
      showToast('请选择日期范围', 'error');
      genBtn.classList.remove('hidden');
      spinner.classList.add('hidden');
      return;
    }
  }

  try {
    const data = await api.post('/reports/generate', body);
    if (data && data.content) {
      document.getElementById('reportResult').innerHTML = `
        <div class="report-content">${renderMarkdown(data.content)}</div>
        ${data.id ? `<div class="mt-2"><button class="btn btn-primary btn-sm download-report" data-id="${data.id}">下载报告 (Markdown)</button></div>` : ''}
      `;
      document.getElementById('reportResult').scrollIntoView({ behavior: 'smooth' });
      document.querySelector('.download-report')?.addEventListener('click', e => {
        api.download(`/reports/${e.target.dataset.id}/download`);
      });
      showToast('报告生成成功', 'success');
      loadHistory();
    }
  } catch (e) {
    showToast(`生成失败: ${e.message}`, 'error');
  }
  genBtn.classList.remove('hidden');
  spinner.classList.add('hidden');
}

async function loadHistory() {
  try {
    const data = await api.get('/reports', { limit: 5 });
    const el = document.getElementById('reportHistory');
    if (data && data.reports && data.reports.length) {
      el.innerHTML = data.reports.map(r => `
        <div class="expander">
          <div class="expander-header">
            <span style="font-weight:600;font-family:var(--font-display)">
              ${(r.week_start || '').slice(0, 10)} — ${(r.week_end || '').slice(0, 10)}
            </span>
            <span class="expander-arrow">+</span>
          </div>
          <div class="expander-body">
            <p class="text-sm text-secondary">学习 ${r.total_study_time || 0} 分钟 · 提问 ${r.total_questions || 0} 次 · ${r.documents_studied || 0} 篇文档</p>
            <div class="report-content mt-2" style="max-height:500px;overflow-y:auto;border:none;padding:0">${renderMarkdown(r.content || '')}</div>
            ${r.file_path ? `<div class="mt-2"><button class="btn btn-primary btn-sm download-history" data-id="${r.id}">下载报告 (Markdown)</button></div>` : ''}
          </div>
        </div>
      `).join('');
      el.querySelectorAll('.expander-header').forEach(h => {
        h.addEventListener('click', () => h.parentElement.classList.toggle('open'));
      });
      el.querySelectorAll('.download-history').forEach(btn => {
        btn.addEventListener('click', e => {
          e.stopPropagation();
          api.download(`/reports/${btn.dataset.id}/download`);
        });
      });
    } else {
      el.innerHTML = showEmpty('', '还没有生成过报告');
    }
  } catch (e) { el.innerHTML = ''; }
}
