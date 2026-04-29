/* 知识测评页面 v2.2 — 试卷风格 */

import { api } from '../api.js';
import { renderTopbar, showEmpty } from '../components.js';
import { showToast } from '../utils.js';

export function renderQuizPage() {
  renderTopbar('quiz');

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>知识测评</h2>
      <p>AI 自动基于文档内容出题，评测掌握程度</p>
    </div>

    <div id="setupCard">
      <div class="quiz-setup">
        <div class="form-group" style="min-width:220px">
          <label class="form-label">选择文档</label>
          <select id="quizDocSelect" class="form-select"><option value="">— 请选择已解析的文档 —</option></select>
        </div>
        <div class="form-group" style="min-width:120px">
          <label class="form-label">题目数量</label>
          <select id="quizCount" class="form-select">
            <option value="4">4 题（快速）</option>
            <option value="8" selected>8 题（标准）</option>
            <option value="12">12 题（全面）</option>
          </select>
        </div>
        <button id="startQuizBtn" class="btn btn-primary" style="align-self:flex-end">开始测评</button>
      </div>
    </div>

    <div id="quizArea" class="hidden"></div>
    <div id="quizResult" class="hidden"></div>
    <div id="quizHistory" class="mt-4"></div>
  `;

  loadDocSelect();
  document.getElementById('startQuizBtn').addEventListener('click', startQuiz);
  loadHistory();
}

async function loadDocSelect() {
  try {
    const data = await api.get('/documents');
    if (data && data.documents) {
      const sel = document.getElementById('quizDocSelect');
      data.documents.filter(d => d.status === 'parsed').forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = d.filename;
        sel.appendChild(opt);
      });
      if (!sel.querySelector('option[value]')) {
        sel.innerHTML = '<option value="">— 请先上传并解析文档 —</option>';
      }
    }
  } catch (e) { /* ignore */ }
}

async function startQuiz() {
  const docId = document.getElementById('quizDocSelect').value;
  const count = parseInt(document.getElementById('quizCount').value);
  if (!docId) { showToast('请选择一个文档', 'error'); return; }

  const btn = document.getElementById('startQuizBtn');
  btn.textContent = 'AI 出题中...';
  btn.disabled = true;

  const setupCard = document.getElementById('setupCard');
  const steps = renderProgressSteps([
    { key: 'analyzing', label: '分析文档结构' },
    { key: 'generating', label: '生成题目' },
    { key: 'extracting', label: '提取知识点' }
  ]);
  setupCard.appendChild(steps);
  updateStepStatus(steps, 'analyzing', 'active');

  try {
    const data = await api.post('/assessments', { document_id: parseInt(docId), question_count: count });
    if (data.error) { showToast(data.error, 'error'); btn.textContent = '开始测评'; btn.disabled = false; steps.remove(); return; }
    updateStepStatus(steps, 'analyzing', 'done');
    updateStepStatus(steps, 'generating', 'done');
    updateStepStatus(steps, 'extracting', 'done');
    await new Promise(r => setTimeout(r, 400));
    steps.remove();
    setupCard.classList.add('hidden');
    renderQuizQuestions(data.assessment_id, data.questions);
  } catch (e) {
    showToast(`出题失败: ${e.message}`, 'error');
    steps.remove();
  }
  btn.textContent = '开始测评';
  btn.disabled = false;
}

function renderQuizQuestions(assessmentId, questions) {
  window._currentAssessmentId = assessmentId;
  const area = document.getElementById('quizArea');
  area.classList.remove('hidden');
  area.innerHTML = `
    <h3 class="section-title">测评中（共 ${questions.length} 题）</h3>
    ${questions.map((q, i) => `
      <div class="quiz-question" data-qid="${q.id}">
        <div class="q-header">
          <span class="badge ${q.question_type === 'choice' ? 'badge-info' : q.question_type === 'true_false' ? 'badge-warning' : 'badge-success'}">${q.question_type === 'choice' ? '选择题' : q.question_type === 'true_false' ? '判断题' : '简答题'}</span>
          <span class="text-xs text-secondary">难度: ${q.difficulty === 'easy' ? '简单' : q.difficulty === 'hard' ? '较难' : '中等'}</span>
        </div>
        <div class="q-text"><span class="q-num">${i + 1}.</span>${q.question_text}</div>
        ${renderQuestionOptions(q)}
      </div>
    `).join('')}
    <div style="margin-top:32px">
      <button id="submitQuizBtn" class="btn btn-primary btn-block">提交答案</button>
    </div>
  `;

  area.querySelectorAll('.quiz-option').forEach(opt => {
    opt.addEventListener('click', () => {
      const parent = opt.parentElement;
      parent.querySelectorAll('.quiz-option').forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
    });
  });

  document.getElementById('submitQuizBtn').addEventListener('click', () => submitQuiz(assessmentId));
}

function renderQuestionOptions(q) {
  if (q.question_type === 'short_answer') {
    return `<textarea class="form-textarea" placeholder="请输入你的答案..." rows="3" style="margin-top:8px"></textarea>`;
  }
  try {
    const options = typeof q.options === 'string' ? JSON.parse(q.options) : (q.options || {});
    if (q.question_type === 'true_false') {
      return `
        <div class="quiz-option" data-key="A">A. 正确</div>
        <div class="quiz-option" data-key="B">B. 错误</div>
      `;
    }
    return Object.entries(options).map(([k, v]) => `
      <div class="quiz-option" data-key="${k}">${k}. ${v}</div>
    `).join('');
  } catch { return ''; }
}

async function submitQuiz(assessmentId) {
  const answers = [];
  document.getElementById('quizArea').querySelectorAll('.quiz-question').forEach(qEl => {
    const qid = parseInt(qEl.dataset.qid);
    const selected = qEl.querySelector('.quiz-option.selected');
    const input = qEl.querySelector('textarea');
    answers.push({
      question_id: qid,
      user_answer: selected ? selected.dataset.key : (input ? input.value : '')
    });
  });

  const btn = document.getElementById('submitQuizBtn');
  btn.disabled = true;

  const btnParent = btn.parentElement;
  btn.remove();
  const steps = renderProgressSteps([
    { key: 'submitting', label: '提交答案' },
    { key: 'judging', label: 'AI 评判中' },
    { key: 'analyzing', label: '生成分析报告' }
  ]);
  btnParent.appendChild(steps);
  updateStepStatus(steps, 'submitting', 'active');

  try {
    updateStepStatus(steps, 'submitting', 'done');
    updateStepStatus(steps, 'judging', 'active');

    const result = await api.post(`/assessments/${assessmentId}/submit`, { answers });
    if (result.error) { showToast(result.error, 'error'); steps.remove(); restoreSubmitBtn(btnParent); return; }

    updateStepStatus(steps, 'judging', 'done');
    updateStepStatus(steps, 'analyzing', 'done');
    await new Promise(r => setTimeout(r, 500));
    steps.remove();

    document.getElementById('quizArea').classList.add('hidden');
    const resultDiv = document.getElementById('quizResult');
    resultDiv.classList.remove('hidden');

    const results = result.results || [];

    resultDiv.innerHTML = `
      <div class="score-reveal">
        <div class="score-ring"><div class="score-number">${result.score}</div></div>
        <p style="margin-top:20px;font-size:1rem;color:var(--ink-soft)">
          正确 <strong style="color:var(--success)">${result.correct_count}</strong> / ${result.total} 题
        </p>
      </div>

      <div class="quiz-feedback-list">
        <h3 class="section-title">答题详情</h3>
        ${results.map((r, i) => {
          const correct = r.is_correct;
          const icon = correct ? '✓' : '✗';
          const color = correct ? 'var(--success)' : 'var(--error)';
          const scorePercent = Math.round((r.score || 0) * 100);
          return `
            <div class="quiz-feedback-item" style="border-left-color:${color}">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <span class="feedback-icon" style="color:${color}">${icon}</span>
                <span class="badge ${correct ? 'badge-success' : 'badge-error'}">${r.score === 1 ? '满分' : r.score > 0 ? scorePercent + '%' : '0分'}</span>
              </div>
              <div class="q-text" style="font-size:1rem;margin-top:8px">${i + 1}. ${r.question || ''}</div>
              ${r.user_answer ? `<p class="text-sm mt-1" style="color:var(--ink-soft)">你的答案：${r.user_answer}</p>` : ''}
              ${!correct ? `<p class="text-sm mt-1" style="color:var(--success);font-weight:600">正确答案：${r.correct_answer || '见解析'}</p>` : ''}
              <p class="text-sm mt-1" style="color:var(--ink-soft);line-height:1.7">${r.feedback || ''}</p>
              ${r.knowledge_point ? `<span class="badge badge-info mt-1">${r.knowledge_point}</span>` : ''}
            </div>
          `;
        }).join('')}
      </div>

      <div class="text-center mt-4">
        <button id="retryQuizBtn" class="btn btn-secondary">重新测评</button>
      </div>
    `;

    document.getElementById('retryQuizBtn').addEventListener('click', () => {
      resultDiv.classList.add('hidden');
      document.getElementById('setupCard').classList.remove('hidden');
      document.getElementById('quizArea').innerHTML = '';
    });

    showToast(`测评完成：${result.score} 分`, result.score >= 80 ? 'success' : 'info');
  } catch (e) {
    showToast(`提交失败: ${e.message}`, 'error');
    steps.remove();
    restoreSubmitBtn(btnParent);
  }
}

function restoreSubmitBtn(parent) {
  const btn = document.createElement('button');
  btn.id = 'submitQuizBtn';
  btn.className = 'btn btn-primary btn-block';
  btn.textContent = '提交答案';
  btn.addEventListener('click', () => submitQuiz(window._currentAssessmentId));
  parent.appendChild(btn);
}

function renderProgressSteps(steps) {
  const container = document.createElement('div');
  container.className = 'progress-steps';
  container.innerHTML = steps.map((s, i) => `
    <div class="progress-step" data-step="${s.key}">
      <span class="progress-dot"></span>
      <span class="progress-label">${s.label}</span>
    </div>
  `).join('');
  return container;
}

function updateStepStatus(container, key, status) {
  const step = container.querySelector(`[data-step="${key}"]`);
  if (!step) return;
  step.className = `progress-step ${status}`;
}

async function loadHistory() {
  try {
    const data = await api.get('/assessments/history', { limit: 10 });
    const el = document.getElementById('quizHistory');
    if (data && data.assessments && data.assessments.length) {
      el.innerHTML = `
        <h3 class="section-title">测评历史</h3>
        ${data.assessments.map(a => `
          <div class="expander">
            <div class="expander-header">
              <span style="display:flex;align-items:center;gap:12px">
                <span class="badge ${a.score >= 80 ? 'badge-success' : a.score >= 60 ? 'badge-warning' : 'badge-error'}">${a.score}分</span>
                <span>${a.filename || '未知文档'}</span>
              </span>
              <span class="text-xs text-secondary">${(a.completed_at || '').slice(0, 16)}</span>
            </div>
          </div>
        `).join('')}
      `;
    }
  } catch (e) { /* ignore */ }
}
