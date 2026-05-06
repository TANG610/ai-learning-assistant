/* 主入口 - 路由与页面切换 */

import { isLoggedIn } from './auth.js';
import { renderLoginPage, renderRegisterPage } from './auth.js';

// 页面模块映射
const pages = {
  chat: () => import('./pages/chat.js').then(m => m.renderChatPage()),
  news: () => import('./pages/news.js').then(m => m.renderNewsPage()),
  library: () => import('./pages/library.js').then(m => m.renderLibraryPage()),
  progress: () => import('./pages/progress.js').then(m => m.renderProgressPage()),
  report: () => import('./pages/report.js').then(m => m.renderReportPage()),
  quiz: () => import('./pages/quiz.js').then(m => m.renderQuizPage()),
  settings: () => import('./pages/settings.js').then(m => m.renderSettingsPage())
};

// 无需登录的页面
const publicPages = ['login', 'register'];

function getCurrentPage() {
  const hash = window.location.hash.slice(2) || 'chat';
  const [page, ...rest] = hash.split('?');
  return page;
}

async function route() {
  const app = document.getElementById('app');
  const page = getCurrentPage();

  // 未登录 → 跳转登录
  if (!isLoggedIn() && !publicPages.includes(page)) {
    window.location.hash = '#/login';
    return;
  }

  // 已登录但访问登录页 → 跳转 chat
  if (isLoggedIn() && publicPages.includes(page)) {
    window.location.hash = '#/chat';
    return;
  }

  // 登录/注册页面 - 无顶栏
  if (page === 'login') {
    renderLoginPage();
    return;
  }
  if (page === 'register') {
    renderRegisterPage();
    return;
  }

  // 显示主应用布局
  app.innerHTML = `
    <div class="app-shell">
      <div id="topbar" class="topbar"></div>
      <div id="mainContent" class="main-content">
        <p class="text-center text-secondary mt-3"><span class="spinner"></span> 加载中...</p>
      </div>
    </div>
  `;

  // 加载对应页面
  if (pages[page]) {
    try {
      const mc = document.getElementById('mainContent');
      if (page === 'chat') mc.classList.add('chat-active');
      await pages[page]();
    } catch (e) {
      document.getElementById('mainContent').innerHTML = `
        <p class="text-error">页面加载失败: ${e.message}</p>
      `;
      console.error(e);
    }
  } else {
    // 默认跳转 chat
    window.location.hash = '#/chat';
  }
}

// 监听 hash 变化
window.addEventListener('hashchange', route);

// 初始化
route();
