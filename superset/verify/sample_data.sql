-- Sample telemetry for the throwaway Superset verification stack (compose.verify.yaml) ONLY.
-- Run as gcc_owner after `alembic upgrade head` and `python -m app.seed dev`. Never run it against a real
-- database: it fakes discovery (vendor/model) and writes 26 h of synthetic readings, health, alerts,
-- parts and firmware so every chart has rows and the RLS check has data from both sites.

BEGIN;

-- "Discovery": vendor/model from the seed's simulated fleet order (FLEET[(i-1) % 6]).
WITH fleet(idx, vendor, model) AS (
  VALUES (0, 'Dell', 'PowerEdge R750'), (1, 'HPE', 'ProLiant DL380 Gen10'), (2, 'Lenovo', 'ThinkSystem SR650 V3'),
         (3, 'Dell', 'PowerEdge R650'), (4, 'HPE', 'ProLiant DL360 Gen10'), (5, 'Lenovo', 'ThinkSystem SR630 V3')
)
UPDATE servers s
   SET vendor = f.vendor, model = f.model, name = COALESCE(s.name, 'srv-' || lpad(s.id::text, 3, '0')),
       serial = COALESCE(s.serial, 'SN' || lpad(s.id::text, 6, '0')), last_seen_at = now()
  FROM fleet f
 WHERE f.idx = (s.id - 1) % 6 AND s.vendor IS NULL;

-- Readings every 5 minutes for 26 hours: inlet, exhaust, fan RPM, power, drive life.
INSERT INTO readings (time, server_id, metric_code, component, value)
SELECT t, s.id, m.code, m.component,
       CASE m.code
         WHEN 1 THEN 21 + (s.id % 7) + 2 * sin(extract(epoch FROM t) / 3600.0)
         WHEN 2 THEN 33 + (s.id % 7) + 3 * sin(extract(epoch FROM t) / 3600.0)
         WHEN 5 THEN 6000 + 150 * (s.id % 9) + 300 * sin(extract(epoch FROM t) / 1800.0)
         WHEN 9 THEN 240 + 35 * (s.id % 6) + 40 * sin(extract(epoch FROM t) / 5400.0)
         WHEN 20 THEN 100 - ((s.id * 7) % 96)
       END
  FROM servers s
 CROSS JOIN generate_series(now() - interval '26 hours', now(), interval '5 minutes') AS t
 CROSS JOIN (VALUES (1::smallint, ''), (2::smallint, ''), (5::smallint, 'Fan1'), (9::smallint, ''),
                    (20::smallint, 'Disk.Bay.0')) AS m(code, component);


-- Current health: system, fan and drive per server; a few Warning/Critical.
INSERT INTO health_status (server_id, metric_code, component, health, state, since, updated_at)
SELECT s.id, m.code, m.component,
       CASE WHEN m.code = 19 AND s.id % 11 = 0 THEN 'Critical'
            WHEN m.code = 7 AND s.id % 8 = 0 THEN 'Warning'
            WHEN m.code = 16 AND s.id % 11 = 0 THEN 'Critical'
            WHEN m.code = 16 AND s.id % 8 = 0 THEN 'Warning'
            ELSE 'OK' END,
       'Enabled', now() - (s.id || ' hours')::interval, now()
  FROM servers s
 CROSS JOIN (VALUES (16::smallint, ''), (7::smallint, 'Fan1'), (19::smallint, 'Disk.Bay.0')) AS m(code, component)
ON CONFLICT DO NOTHING;

-- Parts: two CPUs and one drive per server.
INSERT INTO components (server_id, type, name, model, manufacturer, serial, capacity, capacity_unit, firmware_version)
SELECT s.id, p.type, p.name, p.model, p.manufacturer, p.name || '-' || s.id, p.capacity, p.unit, p.fw
  FROM servers s
 CROSS JOIN (VALUES ('cpu', 'CPU.Socket.1', 'Xeon Gold 6338', 'Intel', 32.0, 'cores', NULL),
                    ('cpu', 'CPU.Socket.2', 'Xeon Gold 6338', 'Intel', 32.0, 'cores', NULL),
                    ('drive', 'Disk.Bay.0', 'PM1733 1.92TB', 'Samsung', 1920.0, 'GB', 'EPK9')) AS
       p(type, name, model, manufacturer, capacity, unit, fw);

-- Firmware: BIOS and BMC; every fifth server is off baseline for BIOS.
INSERT INTO firmware_inventory (server_id, component, component_key, component_type, version, collected_at)
SELECT s.id, f.component, f.component, 'firmware',
       CASE WHEN f.component = 'BIOS' AND s.id % 5 = 0 THEN 'old-1.0' ELSE COALESCE(b.version, 'unknown') END,
       now()
  FROM servers s
 CROSS JOIN (VALUES ('BIOS'), ('BMC')) AS f(component)
  LEFT JOIN firmware_baselines b ON b.vendor = s.vendor AND b.model = s.model AND b.component = f.component
ON CONFLICT DO NOTHING;

-- Alerts over the last 30 days: some open, some acknowledged, most resolved.
INSERT INTO alerts (rule_id, server_id, site_id, metric_code, component, dedupe_key, state, severity, title,
                    occurrences, opened_at, acked_at, acked_by, resolved_at)
SELECT r.id, s.id, s.site_id, r.metric_code, '', 'sample-' || s.id || '-' || n,
       CASE WHEN n % 7 = 0 THEN 'open' WHEN n % 5 = 0 THEN 'acknowledged' ELSE 'resolved' END,
       CASE WHEN n % 4 = 0 THEN 'Critical' ELSE 'Warning' END,
       r.name || ' on ' || COALESCE(s.name, s.bmc_host),
       1 + n % 3,
       now() - (n * 7 || ' hours')::interval,
       CASE WHEN n % 7 = 0 THEN NULL ELSE now() - (n * 7 || ' hours')::interval + ((5 + n % 40) || ' minutes')::interval END,
       CASE WHEN n % 7 = 0 THEN NULL ELSE 'noc' END,
       CASE WHEN n % 7 = 0 OR n % 5 = 0 THEN NULL
            ELSE now() - (n * 7 || ' hours')::interval + ((30 + n % 200) || ' minutes')::interval END
  FROM generate_series(1, 90) AS n
  JOIN LATERAL (SELECT * FROM servers ORDER BY id OFFSET (n % 30) LIMIT 1) s ON true
  JOIN LATERAL (SELECT * FROM alert_rules WHERE metric_code IS NOT NULL ORDER BY id OFFSET (n % 12) LIMIT 1) r ON true;

COMMIT;

-- Continuous-aggregate refreshes cannot run inside a transaction.
CALL refresh_continuous_aggregate('readings_5m', now() - interval '3 days', now());
CALL refresh_continuous_aggregate('readings_1h', now() - interval '3 days', now());
