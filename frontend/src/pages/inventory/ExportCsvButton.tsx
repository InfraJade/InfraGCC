import { useState } from 'react';

import { useApi } from '@/api/ApiProvider';
import { errorMessage } from '@/api/errors';
import { downloadCsv } from '@/api/hooks';
import type { QueryParams } from '@/api/types';
import { Button } from '@/components/Button';
import { useToast } from '@/components/Toast';

/** Downloads the export with the same filters (and sort) as the list on screen. */
export function ExportCsvButton({
  path,
  query,
  filename,
  label = 'Export CSV',
}: {
  path: string;
  query: QueryParams;
  filename: string;
  label?: string;
}) {
  const api = useApi();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      await downloadCsv(api, path, query, filename);
      toast({ tone: 'success', title: `Downloaded ${filename}` });
    } catch (err) {
      toast({ tone: 'error', title: "Couldn't export the CSV", description: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button size="sm" icon="download" loading={busy} onClick={() => void run()}>
      {label}
    </Button>
  );
}
