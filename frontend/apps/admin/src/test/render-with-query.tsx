import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import type { ReactElement, ReactNode } from 'react';

import { AuthProvider } from '../context/AuthContext';

export function createTestQueryClient(): QueryClient {
    return new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
                gcTime: 0,
            },
            mutations: {
                retry: false,
            },
        },
    });
}

type CustomRenderOptions = Omit<RenderOptions, 'wrapper'> & {
    queryClient?: QueryClient;
};

export function renderWithQueryClient(
    ui: ReactElement,
    options?: CustomRenderOptions,
) {
    const queryClient = options?.queryClient ?? createTestQueryClient();
    const Wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const result = render(ui, { wrapper: Wrapper, ...options });
    return { ...result, queryClient };
}

type ContractRenderOptions = Omit<RenderOptions, 'wrapper'> & {
    queryClient?: QueryClient;
    initialRoute?: string;
};

export function renderForContract(
    ui: ReactElement,
    options?: ContractRenderOptions,
) {
    const queryClient = options?.queryClient ?? createTestQueryClient();
    const initialRoute = options?.initialRoute ?? '/';

    window.history.pushState({}, '', initialRoute);

    const Wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
            <AuthProvider>
                <BrowserRouter>
                    {children}
                </BrowserRouter>
            </AuthProvider>
        </QueryClientProvider>
    );

    const result = render(ui, { wrapper: Wrapper, ...options });
    return { ...result, queryClient };
}
