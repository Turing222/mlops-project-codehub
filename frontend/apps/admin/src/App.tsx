import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Spin, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import { QueryClientProvider } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { queryClient } from './query/query-client';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import ChatPage from './pages/Chat';
import GoogleCallbackPage from './pages/Auth/GoogleCallbackPage';
import AuthModal from './pages/Auth/AuthModal';
import { useThemeStore } from './stores/theme-store';

const LazyAdminDashboard = React.lazy(() => import('./pages/Admin'));
const LazyCreditsPage = React.lazy(() => import('./pages/Credits'));
const LazyRepoCheckPage = React.lazy(() => import('./pages/RepoCheck'));

const BRAND_PALETTES = {
  '#1677ff': {
    gradientEnd: '#722ed1',
    light: {
      page: '#f3f8ff',
      container: '#ffffff',
      subtle: '#e8f2ff',
      border: '#cfe3ff',
      sidebar: '#87b7f4',
      sidebarHover: 'rgba(255, 255, 255, 0.14)',
      sidebarActive: 'rgba(255, 255, 255, 0.22)',
    },
    dark: {
      page: '#101923',
      container: '#162230',
      subtle: '#1c3045',
      border: '#284461',
      sidebar: '#0b3d80',
      sidebarHover: 'rgba(255, 255, 255, 0.12)',
      sidebarActive: 'rgba(255, 255, 255, 0.2)',
    },
  },
  '#4f46e5': {
    gradientEnd: '#9333ea',
    light: {
      page: '#f6f5ff',
      container: '#ffffff',
      subtle: '#ecebff',
      border: '#d9d6ff',
      sidebar: '#8981eb',
      sidebarHover: 'rgba(255, 255, 255, 0.14)',
      sidebarActive: 'rgba(255, 255, 255, 0.22)',
    },
    dark: {
      page: '#171529',
      container: '#201d38',
      subtle: '#2b2750',
      border: '#413a75',
      sidebar: '#312e81',
      sidebarHover: 'rgba(255, 255, 255, 0.12)',
      sidebarActive: 'rgba(255, 255, 255, 0.2)',
    },
  },
  '#722ed1': {
    gradientEnd: '#db2777',
    light: {
      page: '#faf5ff',
      container: '#ffffff',
      subtle: '#f1e4ff',
      border: '#dfc8fb',
      sidebar: '#9b65f2',
      sidebarHover: 'rgba(255, 255, 255, 0.14)',
      sidebarActive: 'rgba(255, 255, 255, 0.22)',
    },
    dark: {
      page: '#1e1329',
      container: '#2a1a38',
      subtle: '#3a2450',
      border: '#573579',
      sidebar: '#4c1d95',
      sidebarHover: 'rgba(255, 255, 255, 0.12)',
      sidebarActive: 'rgba(255, 255, 255, 0.2)',
    },
  },
  '#0d9488': {
    gradientEnd: '#0284c7',
    light: {
      page: '#f0fdfa',
      container: '#ffffff',
      subtle: '#ccfbf1',
      border: '#99e6d8',
      sidebar: '#0f766e',
      sidebarHover: 'rgba(255, 255, 255, 0.14)',
      sidebarActive: 'rgba(255, 255, 255, 0.22)',
    },
    dark: {
      page: '#0d1f1e',
      container: '#132b29',
      subtle: '#1a3a36',
      border: '#285c56',
      sidebar: '#115e59',
      sidebarHover: 'rgba(255, 255, 255, 0.12)',
      sidebarActive: 'rgba(255, 255, 255, 0.2)',
    },
  },
  '#ea580c': {
    gradientEnd: '#e11d48',
    light: {
      page: '#fff7ed',
      container: '#ffffff',
      subtle: '#ffedd5',
      border: '#fed7aa',
      sidebar: '#e36432',
      sidebarHover: 'rgba(255, 255, 255, 0.14)',
      sidebarActive: 'rgba(255, 255, 255, 0.22)',
    },
    dark: {
      page: '#29180f',
      container: '#382113',
      subtle: '#4a2b16',
      border: '#78451f',
      sidebar: '#9a3412',
      sidebarHover: 'rgba(255, 255, 255, 0.12)',
      sidebarActive: 'rgba(255, 255, 255, 0.2)',
    },
  },
} as const;

// 管理员路由守卫
const AdminRouteGuard: React.FC = () => {
  const { isAuthenticated, isLoading, user, setShowAuthModal } = useAuth();

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      setShowAuthModal(true);
    }
  }, [isLoading, isAuthenticated, setShowAuthModal]);

  if (isLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  if (!user?.is_superuser) {
    return <Navigate to="/" replace />;
  }

  return (
    <React.Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>}>
      <LazyAdminDashboard />
    </React.Suspense>
  );
};

const App: React.FC = () => {
  const { theme, brandColor } = useThemeStore();
  const { i18n } = useTranslation();

  const antdLocale = i18n.language === 'en-US' ? enUS : zhCN;

  React.useEffect(() => {
    const palette = BRAND_PALETTES[brandColor as keyof typeof BRAND_PALETTES] ?? BRAND_PALETTES['#1677ff'];
    const modePalette = palette[theme];

    // 同步设置全局 CSS 变量
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.setProperty('--color-primary', brandColor);
    document.documentElement.style.setProperty('--color-primary-hover', `${brandColor}cc`);
    document.documentElement.style.setProperty('--color-primary-shadow', `${brandColor}26`);
    document.documentElement.style.setProperty('--color-primary-gradient-end', palette.gradientEnd);
    document.documentElement.style.setProperty('--color-bg-page', modePalette.page);
    document.documentElement.style.setProperty('--color-bg-container', modePalette.container);
    document.documentElement.style.setProperty('--color-bg-subtle', modePalette.subtle);
    document.documentElement.style.setProperty('--color-border', modePalette.border);
    document.documentElement.style.setProperty('--color-sidebar-bg', modePalette.sidebar);
    document.documentElement.style.setProperty('--color-sidebar-border', 'rgba(255, 255, 255, 0.24)');
    document.documentElement.style.setProperty('--color-sidebar-hover', modePalette.sidebarHover);
    document.documentElement.style.setProperty('--color-sidebar-active', modePalette.sidebarActive);
  }, [theme, brandColor]);

  return (
    <ConfigProvider
      locale={antdLocale}
      theme={{
        algorithm: theme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: brandColor,
          borderRadius: 10,
          fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* 聊天页（不需要登录，弹窗登录） */}
              <Route path="/" element={<ChatPage />} />

              {/* Google OAuth 回调 */}
              <Route path="/auth/google/callback" element={<GoogleCallbackPage />} />

              {/* 管理员后台 */}
              <Route path="/admin" element={<AdminRouteGuard />} />

              {/* 积分中心 */}
              <Route path="/credits" element={
                <React.Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>}>
                  <LazyCreditsPage />
                </React.Suspense>
              } />

              {/* AI repo credibility check */}
              <Route path="/repo-check" element={
                <React.Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>}>
                  <LazyRepoCheckPage />
                </React.Suspense>
              } />

              {/* 404 跳转 */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          <AuthModal />
        </AuthProvider>
      </QueryClientProvider>
    </ConfigProvider>
  );
};

export default App;
