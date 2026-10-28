import { useState } from 'react';

import { useCursorList } from '@/api/hooks';
import type { ServerEvent } from '@/api/types';
import { DataTable, type Column } from '@/components/DataTable';
import { FormField, Select, TextInput } from '@/components/FormField';
import { HealthBadge } from '@/components/HealthBadge';
import { Age } from '@/components/Reading';
import { useDebouncedValue } from '@/lib/useDebouncedValue';

const SEVERITIES = [
  { value: 'OK', label: 'OK' },
  { value: 'Warning', label: 'Warning' },
  { value: 'Critical', label: 'Critical' },
];

const columns: Column<ServerEvent>[] = [
  {
    id: 'time',
    header: 'Time',
    hideable: false,
    width: '8rem',
    cell: (e) => <Age time={e.time} staleAfterMs={Infinity} />,
  },
  // Event severities use the health words (OK / Warning / Critical).
  {
    id: 'severity',
    header: 'Severity',
    width: '7rem',
    cell: (e) => <HealthBadge health={e.severity} size="sm" />,
  },
  {
    id: 'message',
    header: 'Message',
    hideable: false,
    cell: (e) => <span className="text-text">{e.message}</span>,
  },
  {
    id: 'message_id',
    header: 'Message ID',
    cell: (e) =>
      e.message_id ? (
        <span className="font-mono text-xs text-text-muted">{e.message_id}</span>
      ) : (
        <span className="text-text-subtle">—</span>
      ),
  },
];

/** The BMC event log (SEL / IML / Lenovo event log), newest first, with filters and "Load more". */
export function EventsTab({ serverId }: { serverId: number }) {
  const [severity, setSeverity] = useState('');
  const [text, setText] = useState('');
  const q = useDebouncedValue(text.trim(), 300);
  const list = useCursorList<ServerEvent>(
    `/api/v1/servers/${serverId}/events`,
    { severity, q },
    { refetchInterval: 60_000 },
  );
  const filtered = Boolean(severity || q);

  return (
    <DataTable
      caption="Event log"
      columns={columns}
      getRowId={(e) => e.id}
      dense
      persistKey="server-events"
      {...list.tableProps}
      emptyTitle={filtered ? 'No events match these filters' : 'No events in the log'}
      emptyDescription={
        filtered
          ? 'Try another severity or search text.'
          : 'Events appear as the collector reads the BMC log.'
      }
      summary={list.items.length ? `${list.items.length}${list.hasNextPage ? '+' : ''} events` : undefined}
      toolbar={
        <>
          <FormField label="Severity" hideLabel className="w-40">
            <Select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              options={SEVERITIES}
              placeholder="All severities"
            />
          </FormField>
          <FormField label="Search messages" hideLabel className="min-w-[12rem] flex-1 sm:max-w-xs">
            <TextInput
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search messages…"
            />
          </FormField>
        </>
      }
    />
  );
}
