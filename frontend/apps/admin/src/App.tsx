import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Spin } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import ChatPage from './pages/Chat';

const LazyAdminDashboard = React.lazy(() => import('./pages/Admin'));

// 管理员路由守卫
const AdminRouteGuard: React.FC = () => {
  const { isAuthenticated, isLoading, user, setShowAuthModal } = useAuth();

  if (isLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>;
  }

  if (!isAuthenticated) {
    setShowAuthModal(true);
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
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 10,
          fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
        },
      }}
    >
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* 聊天页（不需要登录，弹窗登录） */}
            <Route path="/" element={<ChatPage />} />

            {/* 管理员后台 */}
            <Route path="/admin" element={<AdminRouteGuard />} />

            {/* 404 跳转 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ConfigProvider>
  );
};

export default App;
