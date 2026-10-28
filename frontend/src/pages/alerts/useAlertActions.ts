import { useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { apiKey, send, useApiMutation, useApiQuery } from '@/api/hooks';
import type { AlertDetail, Metric } from '@/api/types';

export type AlertAction = 'ack' | 'comment' | 'resolve';

const ENDPOINT: Record<AlertAction, string> = { ack: 'ack', comment: 'comments', resolve: 'resolve' };
const SUCCESS: Record<AlertAction, string> = {
  ack: 'Alert acknowledged',
  comment: 'Comment added',
  resolve: 'Alert resolved',
};

export const alertPath = (id: number) => `/api/v1/alerts/${id}`;

export interface AlertActionVars {
  id: number;
  action: AlertAction;
  /** Optional for acknowledge/resolve, required for comments. */
  note?: string;
}

/**
 * Acknowledge, comment or resolve. Refreshes alert lists and the overview, toasts, and puts the returned
 * AlertDetail straight into the detail cache so an open drawer shows the new state at once.
 */
export function useAlertAction(onDone?: (detail: AlertDetail, action: AlertAction) => void) {
  const qc = useQueryClient();
  return useApiMutation<AlertActionVars, { detail: AlertDetail; action: AlertAction }>(
    async (api, { id, action, note }) => {
      const text = note?.trim() ?? '';
      const body = action === 'comment' ? { note: text } : { note: text === '' ? null : text };
      const detail = await api.json<AlertDetail>(`${alertPath(id)}/${ENDPOINT[action]}`, send('POST', body));
      return { detail, action };
    },
    {
      invalidate: ['alerts', 'overview'],
      success: (r) => SUCCESS[r.action],
      onSuccess: ({ detail, action }) => {
        qc.setQueryData(apiKey(alertPath(detail.id)), detail);
        onDone?.(detail, action);
      },
    },
  );
}

/** Metric code → unit (e.g. "inlet_temp" → "°C") for alert values; empty until /metrics loads. */
export function useMetricUnits(): Record<string, string> {
  const q = useApiQuery<Metric[]>('/api/v1/metrics', undefined, { staleTime: 10 * 60_000 });
  return useMemo(() => Object.fromEntries((q.data ?? []).map((m) => [m.code, m.unit])), [q.data]);
}
