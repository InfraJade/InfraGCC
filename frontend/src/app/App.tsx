import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';

import { ApiProvider } from '@/api/ApiProvider';
import { LiveProvider } from '@/api/LiveProvider';
import { createQueryClient } from '@/api/queryClient';
import { AuthProvider, useAuth } from '@/auth/AuthProvider';
import { ToastProvider } from '@/components/Toast';
import { ThemeProvider } from '@/theme/ThemeProvider';

import { AppRoutes } from './routes';

/** Theme prefs are per signed-in user, so the theme provider sits inside auth. */
function UserScopedProviders({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <ThemeProvider userKey={user?.sub ?? 'anonymous'}>
      <ToastProvider>
        <ApiProvider>
          <LiveProvider>{children}</LiveProvider>
        </ApiProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

export function App({ queryClient }: { queryClient?: QueryClient }) {
  const [qc] = useState(() => queryClient ?? createQueryClient());
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <UserScopedProviders>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </UserScopedProviders>
      </AuthProvider>
    </QueryClientProvider>
  );
}
