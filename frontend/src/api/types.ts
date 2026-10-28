/**
 * Named aliases for the app API schemas (generated into `schema.d.ts` by `npm run gen:api`
 * from docs/contracts/openapi-app.json). Import these instead of reaching into `components['schemas']`.
 */
import type { components } from './schema';

type S = components['schemas'];

export type Me = S['MeOut'];
export type Capability = keyof Me['capabilities'] & string;

export type Overview = S['OverviewOut'];
export type OverviewTotals = S['OverviewTotals'];
export type AlertCounts = S['AlertCounts'];
export type HealthCounts = S['HealthCounts'];
export type Freshness = S['Freshness'];
export type Health = S['Health'];
export type Severity = S['Severity'];
export type AlertState = S['AlertState'];
export type ServerStatus = S['ServerStatus'];
export type ComponentType = S['ComponentType'];
export type RoleName = S['Role'];

export type SearchOut = S['SearchOut'];
export type Metric = S['MetricOut'];

export type SiteRef = S['SiteRef'];
export type SiteSummary = S['SiteSummary'];
export type SiteDetail = S['SiteDetail'];
export type SiteOut = S['SiteOut'];
export type SiteCreate = S['SiteCreate'];
export type SiteUpdate = S['SiteUpdate'];
export type RoomWithRacks = S['RoomWithRacks'];
export type RackSummary = S['RackSummary'];

export type Room = S['RoomOut'];
export type RoomCreate = S['RoomCreate'];
export type RoomUpdate = S['RoomUpdate'];

export type Rack = S['RackOut'];
export type RackDetail = S['RackDetail'];
export type RackServer = S['RackServer'];
export type RackCreate = S['RackCreate'];
export type RackUpdate = S['RackUpdate'];

export type ServerListItem = S['ServerListItem'];
export type ServerDetail = S['ServerDetail'];
export type ServerCreate = S['ServerCreate'];
export type ServerUpdate = S['ServerUpdate'];
export type HealthPart = S['HealthPart'];
export type LatestReading = S['LatestReadingOut'];
export type ReadingValue = S['ReadingValue'];
export type ServerComponent = S['ComponentOut'];
export type ComponentListItem = S['ComponentListItem'];
export type FirmwareItem = S['FirmwareItem'];
export type ServerEvent = S['EventOut'];
export type Readings = S['ReadingsOut'];

export type Alert = S['AlertOut'];
export type AlertDetail = S['AlertDetail'];
export type AlertActivity = S['AlertActivityOut'];

export type AlertRule = S['AlertRuleOut'];
export type AlertRuleCreate = S['AlertRuleCreate'];
export type AlertRuleUpdate = S['AlertRuleUpdate'];
export type RuleType = S['RuleType'];

export type Threshold = S['ThresholdOut'];
export type ThresholdIn = S['ThresholdIn'];
export type ThresholdUpdate = S['ThresholdUpdate'];
export type ThresholdPage = S['ThresholdPage'];
export type ThresholdScope = S['ThresholdScope'];
export type ThresholdDirection = S['ThresholdDirection'];
export type EffectiveLimit = S['EffectiveLimit'];
export type BmcLimit = S['BmcLimitOut'];

export type AlertRoute = S['AlertRouteOut'];
export type AlertRouteCreate = S['AlertRouteCreate'];
export type AlertRouteUpdate = S['AlertRouteUpdate'];
export type RouteChannel = S['RouteChannel'];

export type Maintenance = S['MaintenanceOut'];
export type MaintenanceCreate = S['MaintenanceCreate'];
export type MaintenanceUpdate = S['MaintenanceUpdate'];
export type MaintenanceScope = S['MaintenanceScope'];

export type Collector = S['CollectorOut'];
export type CollectorCreate = S['CollectorCreate'];
export type CollectorUpdate = S['CollectorUpdate'];

export type Baseline = S['BaselineOut'];
export type BaselineCreate = S['BaselineCreate'];
export type BaselineUpdate = S['BaselineUpdate'];
export type Compliance = S['ComplianceOut'];
export type ComplianceServer = S['ComplianceServer'];
export type ComplianceSummary = S['ComplianceSummary'];

export type User = S['UserOut'];
export type AuditEntry = S['AuditOut'];

/** Every list endpoint: cursor pagination. */
export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | readonly (string | number)[]>;
