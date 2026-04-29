/* 认证模块 — 杂志封面布局 v2.2 */

import { api } from './api.js';
import { showToast } from './utils.js';

export function renderLoginPage() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="auth-shell">
      <!-- Hero — 杂志封面左半 -->
      <div class="auth-hero">
        <h1><em>AI</em><br>学习助手</h1>
        <div class="hero-line"></div>
        <p class="hero-sub">产品PM专版</p>
        <p class="hero-tagline">让每一份学习资料<br>都成为你的知识资产</p>
      </div>
      <!-- Form — 窄栏表单 -->
      <div class="auth-form-col">
        <div class="auth-card">
          <div class="card-label">登录账户</div>
          <div id="authError" class="error-banner hidden"></div>
          <div class="form-group">
            <label class="form-label">用户名或邮箱</label>
            <input id="loginUsername" class="form-input" placeholder="请输入用户名" autocomplete="username">
          </div>
          <div class="form-group">
            <label class="form-label">密码</label>
            <input id="loginPassword" class="form-input" type="password" placeholder="请输入密码" autocomplete="current-password">
          </div>
          <button id="loginBtn" class="btn btn-primary btn-block">登 录</button>
          <p class="form-footer">还没有账号？<a id="goRegister">立即注册</a></p>
        </div>
      </div>
    </div>
  `;

  document.getElementById('loginBtn').addEventListener('click', handleLogin);
  document.getElementById('loginPassword').addEventListener('keydown', e => {
    if (e.key === 'Enter') handleLogin();
  });
  document.getElementById('goRegister').addEventListener('click', () => {
    window.location.hash = '#/register';
  });
}

export function renderRegisterPage() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <div class="auth-shell">
      <div class="auth-hero">
        <h1><em>AI</em><br>学习助手</h1>
        <div class="hero-line"></div>
        <p class="hero-sub">产品PM专版</p>
        <p class="hero-tagline">开始构建<br>你的知识体系</p>
      </div>
      <div class="auth-form-col">
        <div class="auth-card">
          <div class="card-label">创建账户</div>
          <div id="authError" class="error-banner hidden"></div>
          <div class="form-group">
            <label class="form-label">用户名</label>
            <input id="regUsername" class="form-input" placeholder="2-30 个字符">
          </div>
          <div class="form-group">
            <label class="form-label">邮箱</label>
            <input id="regEmail" class="form-input" type="email" placeholder="your@email.com">
          </div>
          <div class="form-group">
            <label class="form-label">密码</label>
            <input id="regPassword" class="form-input" type="password" placeholder="至少 6 个字符">
          </div>
          <button id="registerBtn" class="btn btn-primary btn-block">注 册</button>
          <p class="form-footer">已有账号？<a id="goLogin">去登录</a></p>
        </div>
      </div>
    </div>
  `;

  document.getElementById('registerBtn').addEventListener('click', handleRegister);
  document.getElementById('goLogin').addEventListener('click', () => {
    window.location.hash = '#/login';
  });
}

async function handleLogin() {
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;

  if (!username || !password) {
    showAuthError('请填写用户名和密码');
    return;
  }

  const btn = document.getElementById('loginBtn');
  btn.textContent = '登录中...';
  btn.disabled = true;

  try {
    const data = await api.post('/auth/login', { username, password });
    if (data.error) {
      showAuthError(data.error);
      btn.textContent = '登 录';
      btn.disabled = false;
      return;
    }
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    window.location.hash = '#/chat';
    window.location.reload();
  } catch (e) {
    showAuthError(e.message);
    btn.textContent = '登 录';
    btn.disabled = false;
  }
}

async function handleRegister() {
  const username = document.getElementById('regUsername').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const password = document.getElementById('regPassword').value;

  if (!username || !email || !password) {
    showAuthError('请填写所有字段');
    return;
  }
  if (username.length < 2 || username.length > 30) {
    showAuthError('用户名长度 2-30 个字符');
    return;
  }
  if (password.length < 6) {
    showAuthError('密码至少 6 个字符');
    return;
  }

  const btn = document.getElementById('registerBtn');
  btn.textContent = '注册中...';
  btn.disabled = true;

  try {
    const data = await api.post('/auth/register', { username, email, password });
    if (data.error) {
      showAuthError(data.error);
      btn.textContent = '注 册';
      btn.disabled = false;
      return;
    }
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    showToast('注册成功！');
    window.location.hash = '#/chat';
    window.location.reload();
  } catch (e) {
    showAuthError(e.message);
    btn.textContent = '注 册';
    btn.disabled = false;
  }
}

function showAuthError(msg) {
  const el = document.getElementById('authError');
  if (el) {
    el.textContent = msg;
    el.classList.remove('hidden');
  }
}

export function isLoggedIn() {
  return !!localStorage.getItem('access_token');
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
}

export function logout() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user');
  window.location.hash = '#/login';
  window.location.reload();
}
