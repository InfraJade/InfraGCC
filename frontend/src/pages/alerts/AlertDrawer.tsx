import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { useApiQuery, useCan } from '@/api/hooks';
import type { AlertActivity, AlertDetail } from '@/api/types';
import { AlertStateBadge, SeverityBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { Drawer } from '@/components/Drawer';
import { FormField, TextArea } from '@/components/FormField';
import { Icon, type IconName } from '@/components/Icon';
import { KeyValueList } from '@/components/KeyValue';
import { QueryState } from '@/components/QueryState';
import { Age } from '@/components/Reading';
import { Skeleton } from '@/components/Skeleton';
import { formatTimestamp } from '@/lib/format';

import { AlertValue } from './columns';
import { alertPath, useAlertAction, type AlertAction } from './useAlertActions';

const STATE_WORD: Record<string, string> = {
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
};
const stateWord = (s: string | null) => (s ? (STATE_WORD[s] ?? s) : '');

const ACTION: Record<string, { icon: IconName; label: string }> = {
  opened: { icon: 'bell', label: 'opened the alert' },
  acknowledged: { icon: 'eye', label: 'acknowledged' },
  comment: { icon: 'file-text', label: 'commented' },
  resolved: { icon: 'circle-check', label: 'resolved' },
  notified: { icon: 'bell', label: 'sent notifications' },
  escalated: { icon: 'triangle-alert', label: 'escalated' },
  reopened: { icon: 'refresh', label: 'reopened' },
};

const COMPOSER: Record<AlertAction, { title: string; confirm: string; required: boolean; hint: string }> = {
  ack: {
    title: 'Acknowledge',
    confirm: 'Acknowledge alert',
    required: false,
    hint: 'Optional: what you are doing about it. Everyone watching this alert sees the note.',
  },
  comment: {
    title: 'Comment',
    confirm: 'Add comment',
    required: true,
    hint: 'Shown in the activity timeline.',
  },
  resolve: {
    title: 'Resolve',
    confirm: 'Resolve alert',
    required: false,
    hint: 'Optional: how it was fixed.',
  },
};

export function AlertDrawer({
  alertId,
  onClose,
  units,
}: {
  alertId: number | null;
  onClose: () => void;
  units: Record<string, string>;
}) {
  const query = useApiQuery<AlertDetail>(alertId !== null ? alertPath(alertId) : null, undefined, {
    refetchInterval: 30_000,
  });
  const can = useCan();
  const [composer, setComposer] = useState<AlertAction | null>(null);
  const [note, setNote] = useState('');
  const [noteError, setNoteError] = useState<string | null>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const mutation = useAlertAction(() => {
    setComposer(null);
    setNote('');
  });

  useEffect(() => {
    setComposer(null);
    setNote('');
    setNoteError(null);
  }, [alertId]);

  useEffect(() => {
    if (composer) noteRef.current?.focus();
  }, [composer]);

  const alert = query.data;
  const canAck = can('ack_alerts');
  const canComment = can('comment_alerts');
  const canResolve = can('resolve_alerts');
  const operator = canAck || canComment || canResolve;
  const showAck = !!alert && canAck && alert.state === 'open';
  const showResolve = !!alert && canResolve && alert.manually_resolvable && alert.state !== 'resolved';

  const start = (a: AlertAction) => {
    setComposer(a);
    setNote('');
    setNoteError(null);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!alert || !composer) return;
    if (COMPOSER[composer].required && note.trim() === '') {
      setNoteError('Write a comment first.');
      return;
    }
    mutation.mutate({ id: alert.id, action: composer, note });
  };

  let footer = null;
  if (alert && operator) {
    footer = composer ? (
      <form className="flex w-full flex-col gap-3" onSubmit={submit} aria-label={COMPOSER[composer].title}>
        <FormField
          label={COMPOSER[composer].required ? 'Comment' : 'Note (optional)'}
          hint={COMPOSER[composer].hint}
          error={noteError}
          required={COMPOSER[composer].required}
        >
          <TextArea
            ref={noteRef}
            value={note}
            maxLength={4000}
            onChange={(e) => {
              setNote(e.target.value);
              if (noteError) setNoteError(null);
            }}
          />
        </FormField>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setComposer(null)} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={mutation.isPending}>
            {COMPOSER[composer].confirm}
          </Button>
        </div>
      </form>
    ) : (
      <>
        {canComment ? (
          <Button icon="file-text" onClick={() => start('comment')}>
            Comment
          </Button>
        ) : null}
        {showResolve ? (
          <Button icon="circle-check" onClick={() => start('resolve')}>
            Resolve
          </Button>
        ) : null}
        {showAck ? (
          <Button variant="primary" icon="check" onClick={() => start('ack')}>
            Acknowledge
          </Button>
        ) : null}
      </>
    );
  }

  return (
    <Drawer
      open={alertId !== null}
      onClose={onClose}
      widthClassName="max-w-xl"
      title={alert?.title ?? 'Alert'}
      description={
        alert
          ? [`Alert #${alert.id}`, alert.server?.name, alert.site?.code].filter(Boolean).join(' · ')
          : undefined
      }
      footer={footer}
    >
      <QueryState query={query} what="this alert" skeleton={<Skeleton lines={8} label="Loading the alert" />}>
        {(a) => (
          <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={a.severity} />
              <AlertStateBadge state={a.state} muted={a.muted} />
            </div>

            {a.message ? <p className="whitespace-pre-line text-sm text-text">{a.message}</p> : null}

            {!operator ? (
              <p className="rounded-md bg-text/5 px-3 py-2 text-xs text-text-muted">
                <Icon name="info" size={12} className="mr-1 inline align-[-2px]" />
                NOC operators can acknowledge, comment on and resolve alerts.
              </p>
            ) : !a.manually_resolvable && a.state !== 'resolved' ? (
              <p className="text-xs text-text-subtle">
                This alert resolves by itself when the readings recover.
              </p>
            ) : null}

            <section aria-labelledby="alert-facts">
              <h3
                id="alert-facts"
                className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted"
              >
                Details
              </h3>
              <AlertFacts alert={a} unit={a.metric ? units[a.metric] : undefined} />
            </section>

            <section aria-labelledby="alert-activity">
              <h3
                id="alert-activity"
                className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted"
              >
                Activity
              </h3>
              <ActivityTimeline items={a.activity} />
            </section>
          </div>
        )}
      </QueryState>
    </Drawer>
  );
}

function WhoWhen({ who, at }: { who?: string | null; at: string | null }) {
  if (!at) return null;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
      {who ? <span>{who}</span> : null}
      <Age time={at} staleAfterMs={Infinity} />
      <span className="text-xs text-text-subtle">({formatTimestamp(at)})</span>
    </span>
  );
}

function AlertFacts({ alert: a, unit }: { alert: AlertDetail; unit: string | undefined }) {
  return (
    <KeyValueList
      items={[
        { label: 'Rule', value: `${a.rule.name} (${a.rule.rule_type})` },
        {
          label: 'Server',
          value: a.server ? (
            <Link to={`/servers/${a.server.id}`} className="font-medium text-accent hover:underline">
              {a.server.name}
            </Link>
          ) : null,
          hideEmpty: true,
        },
        { label: 'Site', value: a.site ? `${a.site.code} · ${a.site.name}` : null, hideEmpty: true },
        { label: 'Metric', value: a.metric, hideEmpty: true },
        { label: 'Component', value: a.component },
        {
          label: 'Value / limit',
          value: a.value === null && a.threshold === null ? null : <AlertValue alert={a} unit={unit} />,
          hideEmpty: true,
        },
        { label: 'Collector', value: a.collector?.name ?? null, hideEmpty: true },
        { label: 'Occurrences', value: <span className="tabular">{a.occurrences}</span> },
        { label: 'Opened', value: <WhoWhen at={a.opened_at} /> },
        { label: 'Last seen', value: <WhoWhen at={a.last_seen_at} /> },
        {
          label: 'Acknowledged',
          value: a.acked_at ? <WhoWhen who={a.acked_by} at={a.acked_at} /> : 'Not yet',
        },
        {
          label: 'Resolved',
          value: a.resolved_at ? <WhoWhen who={a.resolved_by} at={a.resolved_at} /> : 'Not yet',
        },
        { label: 'Notified', value: a.notified_at ? <WhoWhen at={a.notified_at} /> : 'Not sent' },
        { label: 'Escalated', value: a.escalated_at ? <WhoWhen at={a.escalated_at} /> : 'No' },
      ]}
    />
  );
}

function ActivityTimeline({ items }: { items: AlertActivity[] }) {
  if (items.length === 0) return <p className="text-sm text-text-subtle">No activity yet.</p>;
  const sorted = [...items].sort((x, y) => Date.parse(y.time) - Date.parse(x.time));
  return (
    <ol className="flex flex-col gap-3 border-l hairline pl-4" aria-label="Alert activity, newest first">
      {sorted.map((it) => {
        const meta = ACTION[it.action] ?? { icon: 'activity' as const, label: it.action };
        return (
          <li key={it.id} className="relative text-sm">
            <span className="absolute -left-[1.6rem] top-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-surface text-text-muted ring-1 ring-text/15">
              <Icon name={meta.icon} size={11} />
            </span>
            <div className="flex flex-wrap items-baseline gap-x-1.5">
              <span className="font-medium text-text">{it.actor}</span>
              <span className="text-text-muted">{meta.label}</span>
              {it.from_state || it.to_state ? (
                <span className="text-text-muted">
                  ({stateWord(it.from_state) || '—'} → {stateWord(it.to_state) || '—'})
                </span>
              ) : null}
              <Age time={it.time} staleAfterMs={Infinity} className="text-xs" />
            </div>
            {it.note ? (
              <p className="mt-1 whitespace-pre-line rounded-md bg-text/5 px-3 py-2 text-text">{it.note}</p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
