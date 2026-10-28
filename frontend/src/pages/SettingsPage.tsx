import { useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/Button';
import { Switch } from '@/components/FormField';
import { GlassCard } from '@/components/GlassCard';
import { Icon } from '@/components/Icon';
import { PageHeader } from '@/components/PageHeader';
import { useToast } from '@/components/Toast';
import { setDemoMode, useDemoMode } from '@/demo/demoMode';
import { resetDemoDb } from '@/demo/server';
import { useTheme } from '@/theme/ThemeProvider';

const DEMO_POINTS = [
  'Every screen — overview, sites, racks, servers, alerts, inventory, firmware, analytics, admin and audit — shows sample data instead of the backend.',
  'Three sites, about 60 Dell, HPE and Lenovo servers, with faults to explore: a failed power supply, a slow fan, a hot aisle, a worn drive, an unreachable BMC and more.',
  'Sensor values keep moving, and changes you make (acknowledging alerts, editing thresholds, onboarding servers) work until you reload the page.',
  'Only this browser is affected. Your sign-in, roles and site limits stay the same, and nothing is sent to the backend.',
];

/** Per-browser preferences: demo mode and appearance. */
export default function SettingsPage() {
  const demo = useDemoMode();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { theme, setTheme, reduceTransparency, setReduceTransparency } = useTheme();

  const toggleDemo = (on: boolean) => {
    setDemoMode(on);
    toast({
      tone: on ? 'info' : 'success',
      title: on ? 'Demo mode on' : 'Demo mode off',
      description: on ? 'The app now shows sample data.' : 'The app shows live data from the backend again.',
    });
  };

  const resetDemo = () => {
    resetDemoDb();
    qc.removeQueries({ queryKey: ['live'] });
    void qc.resetQueries();
    toast({ tone: 'success', title: 'Demo data reset', description: 'All demo changes were discarded.' });
  };

  return (
    <>
      <PageHeader title="Settings" subtitle="Preferences for this browser" />
      <div className="grid max-w-3xl gap-6">
        <GlassCard
          as="section"
          aria-labelledby="settings-demo"
          title={
            <span id="settings-demo" className="flex items-center gap-2">
              <Icon name="flask" size={18} className="text-accent" />
              Demo mode
            </span>
          }
        >
          <div className="flex flex-col gap-4">
            <Switch
              checked={demo}
              onChange={toggleDemo}
              label={<span className="font-medium">Use demo data</span>}
              description={
                demo
                  ? 'On: the whole app shows sample data. Turn off to go back to live data.'
                  : 'Off: the app shows live data from the collectors and the backend.'
              }
            />
            <ul className="flex flex-col gap-2 border-t hairline pt-4 text-sm text-text-muted">
              {DEMO_POINTS.map((p) => (
                <li key={p} className="flex items-start gap-2">
                  <Icon name="check" size={14} className="mt-1 shrink-0 text-accent" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
            {demo ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-accent/10 px-3 py-2.5 ring-1 ring-inset ring-accent/25">
                <p className="text-sm text-text">
                  Made changes while exploring? Start over with the original sample data.
                </p>
                <Button variant="secondary" size="sm" icon="refresh" onClick={resetDemo}>
                  Reset demo data
                </Button>
              </div>
            ) : null}
          </div>
        </GlassCard>

        <GlassCard
          as="section"
          aria-labelledby="settings-appearance"
          title={
            <span id="settings-appearance" className="flex items-center gap-2">
              <Icon name="sun" size={18} className="text-accent" />
              Appearance
            </span>
          }
        >
          <div className="flex flex-col gap-4">
            <Switch
              checked={theme === 'light'}
              onChange={(light) => setTheme(light ? 'light' : 'dark')}
              label="Light theme"
              description="Dark is the default for NOC screens."
            />
            <Switch
              checked={reduceTransparency}
              onChange={setReduceTransparency}
              label="Reduce transparency"
              description="Solid panels instead of glass, for older displays or projectors."
            />
          </div>
        </GlassCard>
      </div>
    </>
  );
}
