import { PageHeader } from '@/components/PageHeader';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { Tabs } from '@/components/Tabs';
import { useUrlState } from '@/lib/useUrlState';

import { PartsTab } from './inventory/PartsTab';
import { ServersTab } from './inventory/ServersTab';

type Tab = 'servers' | 'parts';

export default function InventoryPage() {
  const [f, setF] = useUrlState({ tab: 'servers' });
  const { siteIds, sites } = useSiteFilter();
  const tab: Tab = f.tab === 'parts' ? 'parts' : 'servers';
  const scope =
    siteIds.length === 0
      ? 'all sites'
      : sites
          .filter((s) => siteIds.includes(s.id))
          .map((s) => s.code)
          .join(', ') || `${siteIds.length} sites`;

  return (
    <div>
      <PageHeader
        title="Inventory"
        subtitle={`Servers and their parts in ${scope}. Filters and sorting run on the server; exports use the same filters.`}
      />
      <Tabs
        label="Inventory"
        value={tab}
        onChange={(id) => setF({ tab: id === 'servers' ? '' : id })}
        tabs={[
          { id: 'servers', label: 'Servers' },
          { id: 'parts', label: 'Parts' },
        ]}
      >
        {(active) => (active === 'parts' ? <PartsTab /> : <ServersTab />)}
      </Tabs>
    </div>
  );
}
