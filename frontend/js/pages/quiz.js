/* 知识测评页面 v2.3 — 支持全部知识库与跨页面状态恢复 */

import { api } from '../api.js';
import { renderTopbar } from '../components.js';
import { escapeHtml, showToast } from '../utils.js';

const ALL_KNOWLEDGE_VALUE = '__all__';

const quizState = {
  phase: 'idle', // idle | creating | ready | submitting | result
  docId: ALL_KNOWLEDGE_VALUE,
  count: 8,
  assessmentId: null,
  questions: [],
  answers: {},
  result: null,
  operation: null,
  parsedDocs: []
};

export function renderQuizPage() {
  renderTopbar('quiz');

  const requestedDoc = sessionStorage.getItem('quizDoc');
  if (requestedDoc && quizState.phase === 'idle') {
    quizState.docId = requestedDoc;
    sessionStorage.removeItem('quizDoc');
  }

  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>知识测评</h2>
      <p>AI 自动基于知识库内容出题，评测掌握程度</p>
    </div>

    <div id="setupCard">
      <div class="quiz-setup">
        <div class="form-group" style="min-width:220px">
          <label class="form-label">选择知识库</label>
          <select id="quizDocSelect" class="form-select">
            <option value="">加载中...</option>
          </select>
        </div>
        <div class="form-group" style="min-width:120px">
          <label class="form-label">题目数量</label>
          <select id="quizCount" class="form-select">
            <option value="4">4 题（快速）</option>
            <option value="8">8 题（标准）</option>
            <option value="12">12 题（全面）</option>
          </select>
        </div>
        <button id="startQuizBtn" class="btn btn-primary" style="align-self:flex-end">开始测评</button>
      </div>
      <div id="setupProgress"></div>
    </div>

    <div id="quizArea" class="hidden"></div>
    <div id="quizResult" class="hidden"></div>
    <div id="quizHistory" class="mt-4"></div>
  `;

  document.getElementById('quizCount').value = String(quizState.count);
  document.getElementById('startQuizBtn').addEventListener('click', startQuiz);
  document.getElementById('quizDocSelect').addEventListener('change', e => {
    quizState.docId = e.target.value || ALL_KNOWLEDGE_VALUE;
  });
  document.getElementById('quizCount').addEventListener('change', e => {
    quizState.count = parseInt(e.target.value, 10) || 8;
  });

  loadDocSelect();
  renderCurrentQuizState();
  loadHistory();
}

async function loadDocSelect() {
  try {
    const data = await api.get('/documents');
    quizState.parsedDocs = (data.documents || []).filter(d => d.status === 'parsed');
  } catch (e) {
    quizState.parsedDocs = [];
  }

  const sel = document.getElementById('quizDocSelect');
  if (!sel) return;

  if (!quizState.parsedDocs.length) {
    sel.innerHTML = '<option value="">— 请先上传并解析文档 —</option>';
    quizState.docId = '';
    renderCurrentQuizState();
    return;
  }

  sel.innerHTML = `
    <option value="${ALL_KNOWLEDGE_VALUE}">全部知识库（所有已解析资料）</option>
    ${quizState.parsedDocs.map(d => `<option value="${d.id}">${escapeHtml(d.filename)}</option>`).join('')}
  `;

  const selectedValue = String(quizState.docId || ALL_KNOWLEDGE_VALUE);
  sel.value = Array.from(sel.options).some(option => option.value === selectedValue)
    ? selectedValue
    : ALL_KNOWLEDGE_VALUE;
  quizState.docId = sel.value;
  renderCurrentQuizState();
}

async function startQuiz() {
  if (quizState.phase === 'creating' || quizState.phase === 'submitting') return;

  const docSelect = document.getElementById('quizDocSelect');
  const countSelect = document.getElementById('quizCount');
  const docValue = docSelect?.value || '';
  const count = parseInt(countSelect?.value, 10) || 8;

  if (!docValue) {
    showToast('请先上传并解析至少一个文档', 'error');
    return;
  }

  quizState.phase = 'creating';
  quizState.docId = docValue;
  quizState.count = count;
  quizState.assessmentId = null;
  quizState.questions = [];
  quizState.answers = {};
  quizState.result = null;
  renderCurrentQuizState();

  const payload = {
    document_id: docValue === ALL_KNOWLEDGE_VALUE ? null : parseInt(docValue, 10),
    question_count: count
  };

  quizState.operation = api.post('/assessments', payload)
    .then(data => {
      if (data.error) throw new Error(data.error);
      quizState.phase = 'ready';
      quizState.assessmentId = data.assessment_id;
      quizState.questions = data.questions || [];
      quizState.answers = {};
      showToast('题目已生成，可以开始答题', 'success');
    })
    .catch(e => {
      quizState.phase = 'idle';
      showToast(`出题失败: ${e.message}`, 'error');
    })
    .finally(() => {
      quizState.operation = null;
      renderCurrentQuizState();
      loadHistory();
    });
}

function renderCurrentQuizState() {
  const setupCard = document.getElementById('setupCard');
  const setupProgress = document.getElementById('setupProgress');
  const quizArea = document.getElementById('quizArea');
  const resultDiv = document.getElementById('quizResult');
  if (!setupCard || !setupProgress || !quizArea || !resultDiv) return;

  syncSetupControls();

  if (quizState.phase === 'creating') {
    setupCard.classList.remove('hidden');
    quizArea.classList.add('hidden');
    resultDiv.classList.add('hidden');
    setupProgress.innerHTML = progressStepsMarkup([
      { key: 'analyzing', label: '分析知识库内容' },
      { key: 'generating', label: '生成测评题目' },
      { key: 'extracting', label: '提取知识点' }
    ], 'generating', ['analyzing']);
    return;
  }

  setupProgress.innerHTML = '';

  if (quizState.phase === 'ready' || quizState.phase === 'submitting') {
    setupCard.classList.add('hidden');
    resultDiv.classList.add('hidden');
    renderQuizQuestions();
    return;
  }

  if (quizState.phase === 'result') {
    setupCard.classList.add('hidden');
    quizArea.classList.add('hidden');
    renderResult();
    return;
  }

  setupCard.classList.remove('hidden');
  quizArea.classList.add('hidden');
  resultDiv.classList.add('hidden');
}

function syncSetupControls() {
  const isBusy = quizState.phase === 'creating' || quizState.phase === 'submitting';
  const hasDocs = quizState.parsedDocs.length > 0;
  const btn = document.getElementById('startQuizBtn');
  const docSelect = document.getElementById('quizDocSelect');
  const countSelect = document.getElementById('quizCount');

  if (btn) {
    btn.disabled = isBusy || !hasDocs;
    btn.textContent = quizState.phase === 'creating' ? 'AI 出题中...' : '开始测评';
  }
  if (docSelect) docSelect.disabled = isBusy;
  if (countSelect) {
    countSelect.disabled = isBusy;
    countSelect.value = String(quizState.count);
  }
}

function renderQuizQuestions() {
  const area = document.getElementById('quizArea');
  if (!area) return;

  area.classList.remove('hidden');
  area.innerHTML = `
    <h3 class="section-title">测评中（共 ${quizState.questions.length} 题）</h3>
    ${quizState.questions.map((q, i) => `
      <div class="quiz-question" data-qid="${q.id}">
        <div class="q-header">
          <span class="badge ${questionBadge(q.question_type)}">${questionTypeLabel(q.question_type)}</span>
          <span class="text-xs text-secondary">难度: ${difficultyLabel(q.difficulty)}</span>
        </div>
        <div class="q-text"><span class="q-num">${i + 1}.</span>${escapeHtml(q.question_text)}</div>
        ${renderQuestionOptions(q)}
      </div>
    `).join('')}
    <div style="margin-top:32px" id="submitSlot">
      ${quizState.phase === 'submitting'
        ? progressStepsMarkup([
            { key: 'submitting', label: '提交答案' },
            { key: 'judging', label: 'AI 评判中' },
            { key: 'analyzing', label: '生成分析报告' }
          ], 'judging', ['submitting'])
        : '<button id="submitQuizBtn" class="btn btn-primary btn-block">提交答案</button>'}
    </div>
  `;

  area.querySelectorAll('.quiz-option').forEach(opt => {
    opt.addEventListener('click', () => {
      const questionEl = opt.closest('.quiz-question');
      questionEl.querySelectorAll('.quiz-option').forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
      quizState.answers[questionEl.dataset.qid] = opt.dataset.key;
    });
  });

  area.querySelectorAll('textarea[data-qid]').forEach(input => {
    input.addEventListener('input', () => {
      quizState.answers[input.dataset.qid] = input.value;
    });
  });

  document.getElementById('submitQuizBtn')?.addEventListener('click', submitQuiz);
}

function renderQuestionOptions(q) {
  const current = quizState.answers[String(q.id)] || '';
  if (q.question_type === 'short_answer') {
    return `<textarea class="form-textarea" data-qid="${q.id}" placeholder="请输入你的答案..." rows="3" style="margin-top:8px">${escapeHtml(current)}</textarea>`;
  }

  try {
    const options = typeof q.options === 'string' ? JSON.parse(q.options) : (q.options || {});
    const entries = q.question_type === 'true_false'
      ? [['A', '正确'], ['B', '错误']]
      : Object.entries(options);

    return entries.map(([k, v]) => `
      <div class="quiz-option ${current === k ? 'selected' : ''}" data-key="${escapeHtml(k)}">
        ${escapeHtml(k)}. ${escapeHtml(v)}
      </div>
    `).join('');
  } catch {
    return '';
  }
}

async function submitQuiz() {
  if (!quizState.assessmentId || quizState.phase === 'submitting') return;
  collectAnswersFromDom();

  const answers = quizState.questions.map(q => ({
    question_id: q.id,
    user_answer: quizState.answers[String(q.id)] || ''
  }));

  quizState.phase = 'submitting';
  renderCurrentQuizState();

  quizState.operation = api.post(`/assessments/${quizState.assessmentId}/submit`, { answers })
    .then(result => {
      if (result.error) throw new Error(result.error);
      quizState.result = result;
      quizState.phase = 'result';
      showToast(`测评完成：${result.score} 分`, result.score >= 80 ? 'success' : 'info');
    })
    .catch(e => {
      quizState.phase = 'ready';
      showToast(`提交失败: ${e.message}`, 'error');
    })
    .finally(() => {
      quizState.operation = null;
      renderCurrentQuizState();
      loadHistory();
    });
}

function collectAnswersFromDom() {
  const area = document.getElementById('quizArea');
  if (!area) return;

  area.querySelectorAll('.quiz-question').forEach(qEl => {
    const qid = qEl.dataset.qid;
    const selected = qEl.querySelector('.quiz-option.selected');
    const input = qEl.querySelector('textarea');
    quizState.answers[qid] = selected ? selected.dataset.key : (input ? input.value : (quizState.answers[qid] || ''));
  });
}

function renderResult() {
  const resultDiv = document.getElementById('quizResult');
  if (!resultDiv || !quizState.result) return;

  const result = quizState.result;
  const results = result.results || [];
  resultDiv.classList.remove('hidden');
  resultDiv.innerHTML = `
    <div class="score-reveal">
      <div class="score-ring"><div class="score-number">${escapeHtml(result.score)}</div></div>
      <p style="margin-top:20px;font-size:1rem;color:var(--ink-soft)">
        正确 <strong style="color:var(--success)">${escapeHtml(result.correct_count)}</strong> / ${escapeHtml(result.total)} 题
      </p>
    </div>

    <div class="quiz-feedback-list">
      <h3 class="section-title">答题详情</h3>
      ${results.map((r, i) => {
        const correct = !!r.is_correct;
        const color = correct ? 'var(--success)' : 'var(--error)';
        const scorePercent = Math.round((r.score || 0) * 100);
        const userAnswer = r.user_answer ?? '';
        return `
          <div class="quiz-feedback-item" style="border-left-color:${color}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <span class="feedback-icon" style="color:${color}">${correct ? '✓' : '✕'}</span>
              <span class="badge ${correct ? 'badge-success' : 'badge-error'}">${r.score === 1 ? '满分' : r.score > 0 ? scorePercent + '%' : '0分'}</span>
            </div>
            <div class="q-text" style="font-size:1rem;margin-top:8px">${i + 1}. ${escapeHtml(r.question || '')}</div>
            ${userAnswer ? `<p class="text-sm mt-1" style="color:var(--ink-soft)">你的答案：${escapeHtml(userAnswer)}</p>` : ''}
            ${!correct ? `<p class="text-sm mt-1" style="color:var(--success);font-weight:600">正确答案：${escapeHtml(r.correct_answer || '见解析')}</p>` : ''}
            <p class="text-sm mt-1" style="color:var(--ink-soft);line-height:1.7">${escapeHtml(r.feedback || '')}</p>
            ${r.knowledge_point ? `<span class="badge badge-info mt-1">${escapeHtml(r.knowledge_point)}</span>` : ''}
          </div>
        `;
      }).join('')}
    </div>

    <div class="text-center mt-4">
      <button id="retryQuizBtn" class="btn btn-secondary">重新测评</button>
    </div>
  `;

  document.getElementById('retryQuizBtn')?.addEventListener('click', () => {
    quizState.phase = 'idle';
    quizState.assessmentId = null;
    quizState.questions = [];
    quizState.answers = {};
    quizState.result = null;
    renderCurrentQuizState();
  });
}

function questionBadge(type) {
  if (type === 'choice') return 'badge-info';
  if (type === 'true_false') return 'badge-warning';
  return 'badge-success';
}

function questionTypeLabel(type) {
  if (type === 'choice') return '选择题';
  if (type === 'true_false') return '判断题';
  return '简答题';
}

function difficultyLabel(difficulty) {
  if (difficulty === 'easy') return '简单';
  if (difficulty === 'hard') return '较难';
  return '中等';
}

function progressStepsMarkup(steps, activeKey, doneKeys = []) {
  return `
    <div class="progress-steps">
      ${steps.map(s => `
        <div class="progress-step ${s.key === activeKey ? 'active' : doneKeys.includes(s.key) ? 'done' : ''}" data-step="${s.key}">
          <span class="progress-dot"></span>
          <span class="progress-label">${escapeHtml(s.label)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

async function loadHistory() {
  try {
    const data = await api.get('/assessments/history', { limit: 10 });
    const el = document.getElementById('quizHistory');
    if (!el) return;
    if (data && data.assessments && data.assessments.length) {
      el.innerHTML = `
        <h3 class="section-title">测评历史</h3>
        ${data.assessments.map(a => `
          <div class="expander">
            <div class="expander-header">
              <span style="display:flex;align-items:center;gap:12px">
                <span class="badge ${a.score >= 80 ? 'badge-success' : a.score >= 60 ? 'badge-warning' : 'badge-error'}">${escapeHtml(a.score)}分</span>
                <span>${escapeHtml(a.filename || '未知文档')}</span>
              </span>
              <span class="text-xs text-secondary">${escapeHtml((a.completed_at || '').slice(0, 16))}</span>
            </div>
          </div>
        `).join('')}
      `;
    } else {
      el.innerHTML = '';
    }
  } catch (e) {
    // ignore
  }
}
