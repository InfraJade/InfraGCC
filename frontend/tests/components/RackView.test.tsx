import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RackView, rackRange, type RackServer } from '@/components/RackView';

const servers: RackServer[] = [
  {
    id: 1,
    name: 'srv-top',
    positionU: 9,
    heightU: 2,
    health: 'OK',
    inletTempC: 22.4,
    inletTime: Date.now() - 5000,
  },
  {
    id: 2,
    name: 'srv-hot',
    positionU: 5,
    heightU: 1,
    health: 'Critical',
    inletTempC: 36.2,
    inletTime: Date.now() - 5000,
  },
  { id: 3, name: 'srv-unknown', positionU: 1, heightU: 1, health: null },
  { id: 4, name: 'srv-out-of-rack', positionU: 10, heightU: 4, health: 'OK' },
];

function rectOf(id: number) {
  const g = document.querySelector(`[data-server-id="${id}"]`);
  const rect = g?.querySelector('rect');
  if (!rect) throw new Error(`no rect for server ${id}`);
  return { y: Number(rect.getAttribute('y')), h: Number(rect.getAttribute('height')) };
}

describe('RackView', () => {
  it('places servers by U position and height (U1 at the bottom)', () => {
    render(<RackView name="R01" heightU={10} servers={servers} uHeight={20} />);
    // top padding 10; server at U9-U10 starts at the very top
    expect(rectOf(1)).toEqual({ y: 11, h: 38 });
    // U5 (1U) → (10 - 5) * 20 + 10 + 1
    expect(rectOf(2)).toEqual({ y: 111, h: 18 });
    // U1 is the bottom slot
    expect(rectOf(3).y).toBe(191);
  });

  it('skips servers that do not fit the rack and draws empty slots', () => {
    const { container } = render(<RackView name="R01" heightU={10} servers={servers} />);
    expect(container.querySelector('[data-server-id="4"]')).toBeNull();
    // 10 U − (2 + 1 + 1) occupied = 6 empty
    expect(container.querySelectorAll('[data-empty-u]')).toHaveLength(6);
    expect(screen.getByRole('group', { name: /Rack R01, 10 U, 3 servers, 6 U free/ })).toBeInTheDocument();
  });

  it('labels each server with its health word, position and inlet temperature', () => {
    render(<RackView name="R01" heightU={10} servers={servers} onServerClick={() => undefined} />);
    const hot = screen.getByRole('button', { name: /srv-hot, U5, health Critical, inlet 36.2 °C/ });
    expect(hot).toHaveAttribute('data-health', 'Critical');
    expect(hot).toHaveTextContent('Critical');
    expect(hot).toHaveTextContent('36.2 °C');
    expect(
      screen.getByRole('button', { name: /srv-unknown, U1, health Unknown, no inlet reading/ }),
    ).toBeInTheDocument();
  });

  it('opens a server on click and on Enter, and shows a tooltip on focus', async () => {
    const user = userEvent.setup();
    const onServerClick = vi.fn();
    render(<RackView name="R01" heightU={10} servers={servers} onServerClick={onServerClick} />);
    await user.click(screen.getByRole('button', { name: /srv-top/ }));
    expect(onServerClick).toHaveBeenLastCalledWith(servers[0]);

    const hot = screen.getByRole('button', { name: /srv-hot/ });
    hot.focus();
    await user.keyboard('{Enter}');
    expect(onServerClick).toHaveBeenLastCalledWith(servers[1]);
    expect(screen.getByRole('tooltip')).toHaveTextContent('srv-hot');
    expect(screen.getByRole('tooltip')).toHaveTextContent('U5');
  });

  it('formats U ranges', () => {
    expect(rackRange({ positionU: 3, heightU: 1 })).toBe('U3');
    expect(rackRange({ positionU: 3, heightU: 2 })).toBe('U3–U4');
  });
});
