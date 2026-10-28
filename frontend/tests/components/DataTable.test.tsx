import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { ApiError } from '@/api/errors';
import { DataTable, type Column, type SortState } from '@/components/DataTable';

interface Row {
  id: number;
  name: string;
  power: number;
}

const rows: Row[] = [
  { id: 1, name: 'srv-a', power: 300 },
  { id: 2, name: 'srv-b', power: 150 },
];

const columns: Column<Row>[] = [
  { id: 'name', header: 'Server', sortable: true, cell: (r) => r.name, hideable: false },
  { id: 'power', header: 'Power', sortable: true, align: 'right', cell: (r) => `${r.power} W` },
  { id: 'notes', header: 'Notes', cell: () => 'n/a', defaultHidden: true },
];

function SortHarness({ onSort }: { onSort: (s: SortState | null) => void }) {
  const [sort, setSort] = useState<SortState | null>(null);
  return (
    <DataTable
      caption="Servers"
      columns={columns}
      rows={rows}
      getRowId={(r) => r.id}
      sort={sort}
      onSortChange={(s) => {
        setSort(s);
        onSort(s);
      }}
    />
  );
}

describe('DataTable', () => {
  it('renders rows, a caption and hides default-hidden columns', () => {
    render(<DataTable caption="Servers" columns={columns} rows={rows} getRowId={(r) => r.id} />);
    const table = screen.getByRole('table', { name: 'Servers' });
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(within(table).queryByText('Notes')).toBeNull();
    expect(within(table).getByText('300 W')).toBeInTheDocument();
  });

  it('cycles server-side sorting asc → desc → none and reflects it in aria-sort', async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    render(<SortHarness onSort={onSort} />);
    const header = screen.getByRole('columnheader', { name: /Power/ });
    expect(header).toHaveAttribute('aria-sort', 'none');
    const button = within(header).getByRole('button');

    await user.click(button);
    expect(onSort).toHaveBeenLastCalledWith({ id: 'power', direction: 'asc' });
    expect(header).toHaveAttribute('aria-sort', 'ascending');

    await user.click(button);
    expect(onSort).toHaveBeenLastCalledWith({ id: 'power', direction: 'desc' });
    expect(header).toHaveAttribute('aria-sort', 'descending');

    await user.click(button);
    expect(onSort).toHaveBeenLastCalledWith(null);
    // Rows are never reordered client-side.
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('srv-a');
  });

  it('sorts from the keyboard', async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    render(<SortHarness onSort={onSort} />);
    within(screen.getByRole('columnheader', { name: /Server/ }))
      .getByRole('button')
      .focus();
    await user.keyboard('{Enter}');
    expect(onSort).toHaveBeenCalledWith({ id: 'name', direction: 'asc' });
  });

  it('shows "Load more" while there is a next cursor and calls onLoadMore', async () => {
    const user = userEvent.setup();
    const onLoadMore = vi.fn();
    const { rerender } = render(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        hasMore
        onLoadMore={onLoadMore}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    rerender(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        hasMore
        loadingMore
        onLoadMore={onLoadMore}
      />,
    );
    expect(screen.getByRole('button', { name: /Loading/ })).toBeDisabled();

    rerender(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        hasMore={false}
        onLoadMore={onLoadMore}
      />,
    );
    expect(screen.queryByRole('button', { name: /Load more/ })).toBeNull();
  });

  it('shows the empty state', () => {
    render(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={[]}
        getRowId={(r) => r.id}
        emptyTitle="No servers match"
      />,
    );
    expect(screen.getByText('No servers match')).toBeInTheDocument();
  });

  it('shows the problem detail and a retry on error', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const error = new ApiError({
      type: 'about:blank',
      title: 'Service unavailable',
      status: 503,
      detail: 'API down',
    });
    render(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={[]}
        getRowId={(r) => r.id}
        error={error}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('API down');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('activates clickable rows with the keyboard', async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable
        caption="Servers"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        onRowClick={onRowClick}
        rowLabel={(r) => `Open ${r.name}`}
      />,
    );
    screen.getByRole('row', { name: 'Open srv-b' }).focus();
    await user.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenCalledWith(rows[1]);
  });

  it('lets users show hidden columns from the column picker', async () => {
    const user = userEvent.setup();
    render(
      <DataTable caption="Servers" columns={columns} rows={rows} getRowId={(r) => r.id} persistKey="t1" />,
    );
    await user.click(screen.getByRole('button', { name: 'Columns' }));
    await user.click(screen.getByRole('checkbox', { name: 'Notes' }));
    expect(screen.getByRole('columnheader', { name: 'Notes' })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem('gcc.table.t1.hidden') ?? 'null')).toEqual([]);
  });
});
