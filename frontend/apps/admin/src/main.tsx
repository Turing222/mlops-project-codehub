import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AppErrorBoundary } from './components/errors/AppErrorBoundary'
import {
  registerGlobalErrorHandlers,
  reportI18nInitFailure,
} from './lib/observability/global-error-handlers'

import { initI18n } from './lib/i18n.ts'

const renderApp = () => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>
    </StrictMode>,
  )
}

registerGlobalErrorHandlers();

initI18n()
  .then(renderApp)
  .catch((err) => {
    console.error('Failed to initialize i18n:', err);
    reportI18nInitFailure(err);
    renderApp();
  });
