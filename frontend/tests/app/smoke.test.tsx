import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { App } from '@/app/App';
import { ToastProvider } from '@/components/Toast';
import GalleryPage from '@/pages/dev/GalleryPage';

vi.mock('@/lib/echarts', () => ({
  initChart: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
}));

describe('app smoke', () => {
  it('sends a signed-out visitor to the login page', async () => {
    window.history.pushState({}, '', '/inventory');
    render(<App queryClient={new QueryClient()} />);
    expect(
      await screen.findByRole('button', { name: 'Sign in with company SSO' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });

  it('renders the component gallery in both themes', () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <GalleryPage />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(container.querySelector('[data-theme="dark"]')).not.toBeNull();
    expect(container.querySelector('[data-theme="light"]')).not.toBeNull();
    expect(screen.getAllByRole('table', { name: 'Sample servers' })).toHaveLength(2);
    expect(screen.getAllByRole('group', { name: /Rack R03/ })).toHaveLength(2);
  }, 15_000);
});
