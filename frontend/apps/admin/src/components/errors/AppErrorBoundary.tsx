import { Component } from 'react';
import type { CSSProperties, ErrorInfo, ReactNode } from 'react';

import { normalizeErrorMessage, reportFrontendErrorEvent } from '../../lib/http/telemetry';

type AppErrorBoundaryProps = {
    children: ReactNode;
    fallback?: ReactNode;
};

type AppErrorBoundaryState = {
    hasError: boolean;
};

const fallbackContainerStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    minHeight: '100vh',
    padding: 24,
    textAlign: 'center',
    fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
};

/**
 * 根级 Error Boundary：捕获 provider/router/page 的 render crash，
 * 上报 `render_error` 事件并渲染极简 fallback，避免整页白屏且不改变现有产品行为。
 */
export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
    state: AppErrorBoundaryState = { hasError: false };

    static getDerivedStateFromError(): AppErrorBoundaryState {
        return { hasError: true };
    }

    componentDidCatch(error: Error, info: ErrorInfo): void {
        reportFrontendErrorEvent({
            eventType: 'render_error',
            source: 'react_error_boundary',
            message: normalizeErrorMessage(error),
            metadata: {
                componentStack: info.componentStack ?? '',
            },
        });
    }

    render(): ReactNode {
        if (!this.state.hasError) {
            return this.props.children;
        }

        if (this.props.fallback !== undefined) {
            return this.props.fallback;
        }

        return (
            <div role="alert" style={fallbackContainerStyle}>
                <h1 style={{ fontSize: 20, margin: 0 }}>页面出现错误</h1>
                <p style={{ margin: 0, opacity: 0.75 }}>抱歉，应用遇到了未预期的问题。</p>
                <button
                    type="button"
                    onClick={() => window.location.reload()}
                    style={{ padding: '8px 20px', borderRadius: 8, cursor: 'pointer' }}
                >
                    刷新页面
                </button>
            </div>
        );
    }
}
