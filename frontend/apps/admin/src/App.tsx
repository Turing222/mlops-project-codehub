import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme } from 'antd';
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
import CenteredLoading from './components/CenteredLoading';
import { useThemeStore } from './stores/theme-store';
import { brandKeyFor } from './theme/brand';

const LazyAdminDashboard = React.lazy(() => import('./pages/Admin'));
const LazyCreditsPage = React.lazy(() => import('./pages/Credits'));
const LazyRepoCheckPage = React.lazy(() => import('./pages/RepoCheck'));

// 管理员路由守卫
const AdminRouteGuard: React.FC = () => {
  const { isAuthenticated, isLoading, user, setShowAuthModal } = useAuth();

  React.useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      setShowAuthModal(true);
    }
  }, [isLoading, isAuthenticated, setShowAuthModal]);

  if (isLoading) {
    return <CenteredLoading />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  if (!user?.is_superuser) {
    return <Navigate to="/" replace />;
  }

  return (
    <React.Suspense fallback={<CenteredLoading />}>
      <LazyAdminDashboard />
    </React.Suspense>
  );
};

const App: React.FC = () => {
  const { theme, brandColor } = useThemeStore();
  const { i18n } = useTranslation();

  const antdLocale = i18n.language === 'en-US' ? enUS : zhCN;

  React.useEffect(() => {
    // 主题真相在 CSS:JS 只写两个属性,变量全部由 index.css 按属性推导。
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-brand', brandKeyFor(brandColor));
  }, [theme, brandColor]);

  return (
    <ConfigProvider
      locale={antdLocale}
      theme={{
        cssVar: {},
        algorithm: theme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: brandColor,
          borderRadius: 10,
          fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
        },
        components: {
          Button: {
            primaryShadow: '0 1px 3px var(--color-primary-shadow)',
          },
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
                <React.Suspense fallback={<CenteredLoading />}>
                  <LazyCreditsPage />
                </React.Suspense>
              } />

              {/* AI repo credibility check */}
              <Route path="/repo-check" element={
                <React.Suspense fallback={<CenteredLoading />}>
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
