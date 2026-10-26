"""Generate the Jade GCC Superset import bundle from spec.yaml.

Output is a Superset 4.1 "assets" export (the format of `superset export` / `POST /api/v1/assets/import/`):

    gcc_bundle/metadata.yaml
    gcc_bundle/databases/GCC_Analytics.yaml
    gcc_bundle/datasets/GCC_Analytics/<view>.yaml
    gcc_bundle/charts/<chart>.yaml
    gcc_bundle/dashboards/<slug>.yaml

Identifiers are uuid5 values derived from names in the spec, so re-importing overwrites in place. Each chart
gets both `params` (what the dashboard renders from) and a saved `query_context` that mirrors what the
Superset 4.1 frontend builds from those params. The query context is required by
`GET /api/v1/chart/{id}/data/`, CSV reports and embedded dashboards: Superset rejects a guest (embedded)
data request whose columns/metrics/orderby are not part of the saved chart.

Standard library + PyYAML only (both available in the Superset image).

    python generate_bundle.py --out gcc_bundle.zip [--dir extracted/] [--spec spec.yaml]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = "gcc_bundle"
VERSION = "1.0.0"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://jade-gcc.example/superset")
DATASOURCE_PLACEHOLDER = "1__table"  # replaced with the real dataset id on import

VIZ_TYPES = {
    "line": "echarts_timeseries_line",
    "bar": "echarts_timeseries_bar",
    "pie": "pie",
    "big_number_total": "big_number_total",
    "table": "table",
    "raw_table": "table",
    "heatmap": "heatmap_v2",
}
UNARY_OPERATORS = {"IS NULL", "IS NOT NULL", "IS TRUE", "IS FALSE"}
OPERATORS = {"==", "!=", ">", "<", ">=", "<=", "IN", "NOT IN", "LIKE", "ILIKE", *UNARY_OPERATORS}

Spec = dict[str, Any]
Json = dict[str, Any]


class SpecError(ValueError):
    """The spec is inconsistent (unknown dataset, metric, column or option)."""


def stable_uuid(kind: str, name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{name}"))


def database_uuid(spec: Spec) -> str:
    return stable_uuid("database", spec["database"]["name"])


def dataset_uuid(name: str) -> str:
    return stable_uuid("dataset", name)


def chart_uuid(key: str) -> str:
    return stable_uuid("chart", key)


def dashboard_uuid(slug: str) -> str:
    return stable_uuid("dashboard", slug)


def embedded_uuid(slug: str) -> str:
    """Deterministic embedded-dashboard id; init_superset.py uses it when it first enables embedding."""
    return stable_uuid("embedded", slug)


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")


# ---------------------------------------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------------------------------------
def expand_columns(spec: Spec, dataset: Spec) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in dataset["columns"]:
        if isinstance(item, dict):
            rows.extend(spec["column_sets"][item["use"]])
        else:
            rows.append(item)
    return rows


def expand_metrics(spec: Spec, dataset: Spec) -> dict[str, Spec]:
    metrics = dataset["metrics"]
    if "use" in metrics:
        return dict(spec["metric_sets"][metrics["use"]])
    return dict(metrics)


def build_dataset(spec: Spec, name: str, dataset: Spec) -> Json:
    columns = []
    for row in expand_columns(spec, dataset):
        column_name, col_type, verbose = row[0], row[1], row[2]
        is_dttm = len(row) > 3 and row[3] == "dttm"
        columns.append(
            {
                "column_name": column_name,
                "verbose_name": verbose,
                "is_dttm": is_dttm,
                "is_active": True,
                "type": col_type,
                "advanced_data_type": None,
                "groupby": True,
                "filterable": True,
                "expression": None,
                "description": None,
                "python_date_format": None,
                "extra": {},
            }
        )
    metrics = [
        {
            "metric_name": metric_name,
            "verbose_name": m.get("label"),
            "metric_type": None,
            "expression": m["expression"],
            "description": m.get("description"),
            "d3format": m.get("d3format"),
            "currency": None,
            "extra": {},
            "warning_text": None,
        }
        for metric_name, m in expand_metrics(spec, dataset).items()
    ]
    return {
        "table_name": name,
        "main_dttm_col": dataset.get("main_dttm_col"),
        "description": dataset.get("description"),
        "default_endpoint": None,
        "offset": 0,
        "cache_timeout": None,
        "catalog": None,
        "schema": "reporting",
        "sql": None,
        "params": None,
        "template_params": None,
        "filter_select_enabled": True,
        "fetch_values_predicate": None,
        "extra": None,
        "normalize_columns": False,
        "always_filter_main_dttm": False,
        "uuid": dataset_uuid(name),
        "metrics": metrics,
        "columns": columns,
        "version": VERSION,
        "database_uuid": database_uuid(spec),
    }


# ---------------------------------------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------------------------------------
class ChartBuilder:
    """Turns one chart entry of the spec into Superset params + query_context."""

    def __init__(self, spec: Spec, key: str, chart: Spec) -> None:
        self.spec = spec
        self.key = key
        self.chart = chart
        self.kind = chart["viz"]
        if self.kind not in VIZ_TYPES:
            raise SpecError(f"chart {key}: unknown viz {self.kind!r}")
        self.dataset_name = chart["dataset"]
        if self.dataset_name not in spec["datasets"]:
            raise SpecError(f"chart {key}: unknown dataset {self.dataset_name!r}")
        dataset = spec["datasets"][self.dataset_name]
        self.dttm: str | None = dataset.get("main_dttm_col")
        self.column_names = {row[0] for row in expand_columns(spec, dataset)}
        self.metric_names = set(expand_metrics(spec, dataset))

    # -- validation helpers --
    def _metric(self, name: str) -> str:
        if name not in self.metric_names:
            raise SpecError(f"chart {self.key}: dataset {self.dataset_name} has no metric {name!r}")
        return name

    def _column(self, name: str) -> str:
        if name not in self.column_names:
            raise SpecError(f"chart {self.key}: dataset {self.dataset_name} has no column {name!r}")
        return name

    # -- filters --
    def time_range(self) -> str | None:
        if not self.dttm:
            if "time_range" in self.chart:
                raise SpecError(f"chart {self.key}: dataset {self.dataset_name} has no time column")
            return None
        return str(self.chart.get("time_range", "No filter"))

    def adhoc_filters(self) -> list[Json]:
        out: list[Json] = []
        time_range = self.time_range()
        if self.dttm and time_range is not None:
            out.append(
                {
                    "clause": "WHERE",
                    "subject": self.dttm,
                    "operator": "TEMPORAL_RANGE",
                    "comparator": time_range,
                    "expressionType": "SIMPLE",
                }
            )
        for item in self.chart.get("filters", []):
            if isinstance(item, dict):
                out.append({"clause": "WHERE", "expressionType": "SQL", "sqlExpression": item["sql"]})
                continue
            column, operator = self._column(item[0]), str(item[1])
            if operator not in OPERATORS:
                raise SpecError(f"chart {self.key}: unsupported operator {operator!r}")
            fltr: Json = {
                "clause": "WHERE",
                "subject": column,
                "operator": operator,
                "expressionType": "SIMPLE",
            }
            if operator not in UNARY_OPERATORS:
                fltr["comparator"] = item[2]
            out.append(fltr)
        return out

    def query_filters(self) -> tuple[list[Json], str]:
        """The `filters` list and `extras.where` the frontend derives from adhoc_filters."""
        filters: list[Json] = []
        where: list[str] = []
        for fltr in self.adhoc_filters():
            if fltr["expressionType"] == "SQL":
                where.append(f"({fltr['sqlExpression']})")
                continue
            entry: Json = {"col": fltr["subject"], "op": fltr["operator"]}
            if "comparator" in fltr:
                entry["val"] = fltr["comparator"]
            filters.append(entry)
        return filters, " AND ".join(where)

    def base_query(self) -> Json:
        filters, where = self.query_filters()
        query: Json = {
            "filters": filters,
            "extras": {"having": "", "where": where},
            "applied_time_extras": {},
            "columns": [],
            "metrics": [],
            "annotation_layers": [],
            "series_limit": 0,
            "order_desc": True,
            "url_params": {},
            "custom_params": {},
            "custom_form_data": {},
        }
        return query

    def common_params(self) -> Json:
        return {
            "datasource": DATASOURCE_PLACEHOLDER,
            "viz_type": VIZ_TYPES[self.kind],
            "adhoc_filters": self.adhoc_filters(),
            "extra_form_data": {},
            "dashboards": [],
        }

    # -- per viz --
    def build(self) -> tuple[Json, Json]:
        builder = getattr(self, f"_build_{self.kind}")
        params, query = builder()
        query_context = {
            "datasource": {"id": 1, "type": "table"},
            "force": False,
            "queries": [query],
            "form_data": params,
            "result_format": "json",
            "result_type": "full",
        }
        return params, query_context

    def _timeseries(self, series_type: str) -> tuple[Json, Json]:
        metrics = [self._metric(m) for m in self.chart["metrics"]]
        groupby = [self._column(c) for c in self.chart.get("groupby", [])]
        x_axis = self.chart.get("x_axis", self.dttm)
        if not x_axis:
            raise SpecError(f"chart {self.key}: needs x_axis (dataset has no time column)")
        self._column(x_axis)
        grain = self.chart.get("time_grain")
        params = self.common_params()
        params.update(
            {
                "x_axis": x_axis,
                "metrics": metrics,
                "groupby": groupby,
                "order_desc": True,
                "row_limit": int(self.chart.get("row_limit", 10000)),
                "truncate_metric": True,
                "show_empty_columns": True,
                "comparison_type": "values",
                "annotation_layers": [],
                "forecastPeriods": 10,
                "forecastInterval": 0.8,
                "x_axis_title_margin": 15,
                "y_axis_title": self.chart.get("y_title", ""),
                "y_axis_title_margin": 30,
                "y_axis_title_position": "Left",
                "sort_series_type": "sum",
                "color_scheme": "supersetColors",
                "only_total": True,
                "show_legend": True,
                "legendType": "scroll",
                "legendOrientation": "top",
                "x_axis_time_format": "smart_date",
                "rich_tooltip": True,
                "tooltipTimeFormat": "smart_date",
                "y_axis_format": self.chart.get("y_format", "SMART_NUMBER"),
                "truncateXAxis": True,
                "y_axis_bounds": [None, None],
            }
        )
        if grain:
            params["time_grain_sqla"] = grain
        if series_type == "line":
            params.update({"seriesType": "line", "markerSize": 6, "opacity": 0.2, "zoomable": True})
        else:
            params.update({"orientation": "vertical", "stack": "Stack" if self.chart.get("stacked") else None})

        axis: Json = {"columnType": "BASE_AXIS", "sqlExpression": x_axis, "label": x_axis, "expressionType": "SQL"}
        query = self.base_query()
        if grain:
            axis["timeGrain"] = grain
            query["extras"]["time_grain_sqla"] = grain
        post: list[Json] = [
            {
                "operation": "pivot",
                "options": {
                    "index": [x_axis],
                    "columns": groupby,
                    "aggregates": {m: {"operator": "mean"} for m in metrics},
                    "drop_missing_columns": False,
                },
            }
        ]
        if groupby and len(metrics) == 1:
            post.append(
                {"operation": "rename", "options": {"columns": {metrics[0]: None}, "level": 0, "inplace": True}}
            )
        post.append({"operation": "flatten"})
        query.update(
            {
                "columns": [axis, *groupby],
                "metrics": metrics,
                "orderby": [[metrics[0], False]],
                "row_limit": params["row_limit"],
                "series_columns": groupby,
                "time_offsets": [],
                "post_processing": post,
            }
        )
        return params, query

    def _build_line(self) -> tuple[Json, Json]:
        return self._timeseries("line")

    def _build_bar(self) -> tuple[Json, Json]:
        return self._timeseries("bar")

    def _build_pie(self) -> tuple[Json, Json]:
        metric = self._metric(self.chart["metric"])
        groupby = [self._column(c) for c in self.chart["groupby"]]
        params = self.common_params()
        params.update(
            {
                "groupby": groupby,
                "metric": metric,
                "row_limit": int(self.chart.get("row_limit", 100)),
                "sort_by_metric": True,
                "color_scheme": "supersetColors",
                "show_labels_threshold": 5,
                "show_legend": True,
                "legendType": "scroll",
                "legendOrientation": "top",
                "label_type": "key_value",
                "number_format": "SMART_NUMBER",
                "date_format": "smart_date",
                "show_labels": True,
                "labels_outside": True,
                "outerRadius": 70,
                "donut": True,
                "innerRadius": 40,
            }
        )
        query = self.base_query()
        query.update(
            {
                "columns": groupby,
                "metrics": [metric],
                "orderby": [[metric, False]],
                "row_limit": params["row_limit"],
            }
        )
        return params, query

    def _build_big_number_total(self) -> tuple[Json, Json]:
        metric = self._metric(self.chart["metric"])
        params = self.common_params()
        params.update(
            {
                "metric": metric,
                "header_font_size": 0.4,
                "subheader_font_size": 0.15,
                "y_axis_format": self.chart.get("format", "SMART_NUMBER"),
                "time_format": "smart_date",
            }
        )
        query = self.base_query()
        query.update({"metrics": [metric], "post_processing": []})
        return params, query

    def _build_table(self) -> tuple[Json, Json]:
        metrics = [self._metric(m) for m in self.chart["metrics"]]
        groupby = [self._column(c) for c in self.chart.get("groupby", [])]
        sort_by = self.chart.get("sort_by")
        ascending = bool(self.chart.get("sort_ascending", False))
        params = self.common_params()
        params.update(
            {
                "query_mode": "aggregate",
                "groupby": groupby,
                "metrics": metrics,
                "all_columns": [],
                "percent_metrics": [],
                "order_by_cols": [],
                "order_desc": not ascending,
                "row_limit": int(self.chart.get("row_limit", 1000)),
                "server_page_length": 10,
                "table_timestamp_format": "smart_date",
                "show_cell_bars": True,
                "color_pn": True,
                "allow_render_html": False,
            }
        )
        if sort_by:
            params["timeseries_limit_metric"] = self._metric(sort_by)
            orderby = [[sort_by, ascending]]
        else:
            orderby = [[metrics[0], False]]
        query = self.base_query()
        query["order_desc"] = not ascending
        query.update(
            {
                "columns": groupby,
                "metrics": metrics,
                "orderby": orderby,
                "row_limit": params["row_limit"],
                "post_processing": [],
                "time_offsets": [],
            }
        )
        return params, query

    def _build_raw_table(self) -> tuple[Json, Json]:
        columns = [self._column(c) for c in self.chart["columns"]]
        order_by = [[self._column(str(c)), bool(asc)] for c, asc in self.chart.get("order_by", [])]
        params = self.common_params()
        params.update(
            {
                "query_mode": "raw",
                "groupby": [],
                "all_columns": columns,
                "percent_metrics": [],
                "order_by_cols": [json.dumps(item) for item in order_by],
                "row_limit": int(self.chart.get("row_limit", 1000)),
                "server_page_length": 10,
                "table_timestamp_format": "smart_date",
                "show_cell_bars": False,
                "color_pn": True,
                "allow_render_html": False,
            }
        )
        query = self.base_query()
        query.pop("metrics")
        query["order_desc"] = False
        query.update(
            {
                "columns": columns,
                "orderby": order_by,
                "row_limit": params["row_limit"],
                "post_processing": [],
                "time_offsets": [],
            }
        )
        return params, query

    def _build_heatmap(self) -> tuple[Json, Json]:
        metric = self._metric(self.chart["metric"])
        x_axis = self._column(self.chart["x_axis"])
        y_axis = self._column(self.chart["groupby"])
        params = self.common_params()
        params.update(
            {
                "x_axis": x_axis,
                "groupby": y_axis,
                "metric": metric,
                "row_limit": int(self.chart.get("row_limit", 10000)),
                "sort_x_axis": "alpha_asc",
                "sort_y_axis": "alpha_asc",
                "normalize_across": "heatmap",
                "legend_type": "continuous",
                "linear_color_scheme": "superset_seq_1",
                "xscale_interval": -1,
                "yscale_interval": -1,
                "left_margin": "auto",
                "bottom_margin": "auto",
                "value_bounds": [None, None],
                "y_axis_format": self.chart.get("format", "SMART_NUMBER"),
                "x_axis_time_format": "smart_date",
                "show_legend": True,
                "show_percentage": False,
                "show_values": True,
            }
        )
        axis = {"columnType": "BASE_AXIS", "sqlExpression": x_axis, "label": x_axis, "expressionType": "SQL"}
        query = self.base_query()
        query.update(
            {
                "columns": [axis, y_axis],
                "metrics": [metric],
                "orderby": [[x_axis, True], [y_axis, True]],
                "row_limit": params["row_limit"],
                "post_processing": [{"operation": "rank", "options": {"metric": metric}}],
            }
        )
        return params, query


def build_chart(spec: Spec, key: str, chart: Spec) -> Json:
    params, query_context = ChartBuilder(spec, key, chart).build()
    return {
        "slice_name": chart["title"],
        "description": chart.get("description"),
        "certified_by": None,
        "certification_details": None,
        "viz_type": VIZ_TYPES[chart["viz"]],
        "params": params,
        "query_context": json.dumps(query_context),
        "cache_timeout": None,
        "uuid": chart_uuid(key),
        "version": VERSION,
        "dataset_uuid": dataset_uuid(chart["dataset"]),
    }


# ---------------------------------------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------------------------------------
def build_dashboard(spec: Spec, board: Spec, chart_ids: dict[str, int]) -> Json:
    slug = board["slug"]
    position: Json = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"children": ["GRID_ID"], "id": "ROOT_ID", "type": "ROOT"},
        "GRID_ID": {"children": [], "id": "GRID_ID", "parents": ["ROOT_ID"], "type": "GRID"},
        "HEADER_ID": {"id": "HEADER_ID", "meta": {"text": board["title"]}, "type": "HEADER"},
    }
    keys_on_board: list[str] = []
    for index, row in enumerate(board["rows"], start=1):
        row_id = f"ROW-{safe_name(slug)}-{index}"
        position["GRID_ID"]["children"].append(row_id)
        width_total = sum(int(w) for w in row["charts"].values())
        if width_total > 12:
            raise SpecError(f"dashboard {slug}: row {index} is {width_total} columns wide (max 12)")
        children = []
        for key, width in row["charts"].items():
            if key not in spec["charts"]:
                raise SpecError(f"dashboard {slug}: unknown chart {key!r}")
            chart_component = f"CHART-{safe_name(key)}"
            children.append(chart_component)
            keys_on_board.append(key)
            position[chart_component] = {
                "children": [],
                "id": chart_component,
                "meta": {
                    "chartId": chart_ids[key],
                    "height": int(row["height"]),
                    "sliceName": spec["charts"][key]["title"],
                    "uuid": chart_uuid(key),
                    "width": int(width),
                },
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "type": "CHART",
            }
        position[row_id] = {
            "children": children,
            "id": row_id,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": ["ROOT_ID", "GRID_ID"],
            "type": "ROW",
        }

    filter_dataset = board["filter_dataset"]
    native_filters: list[Json] = [
        {
            "id": f"NATIVE_FILTER-{safe_name(slug)}-site",
            "name": "Site",
            "filterType": "filter_select",
            "type": "NATIVE_FILTER",
            "description": "Limit every chart to the selected sites.",
            "targets": [{"column": {"name": "site_code"}, "datasetUuid": dataset_uuid(filter_dataset)}],
            "controlValues": {
                "enableEmptyFilter": False,
                "defaultToFirstItem": False,
                "multiSelect": True,
                "searchAllOptions": False,
                "inverseSelection": False,
            },
            "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        }
    ]
    if board.get("time_filter"):
        # Charts on datasets without a time column, or pinned to "No filter", keep their own range.
        excluded = []
        for key in keys_on_board:
            chart = spec["charts"][key]
            dataset = spec["datasets"][chart["dataset"]]
            if not dataset.get("main_dttm_col") or chart.get("time_range", "No filter") == "No filter":
                excluded.append(chart_ids[key])
        native_filters.append(
            {
                "id": f"NATIVE_FILTER-{safe_name(slug)}-time",
                "name": "Time range",
                "filterType": "filter_time",
                "type": "NATIVE_FILTER",
                "description": "Overrides each chart's own time range.",
                "targets": [{}],
                "controlValues": {"enableEmptyFilter": False},
                "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
            }
        )

    return {
        "dashboard_title": board["title"],
        "description": None,
        "css": "",
        "slug": slug,
        "certified_by": "",
        "certification_details": "",
        "published": True,
        "uuid": dashboard_uuid(slug),
        "position": position,
        "metadata": {
            "refresh_frequency": int(board["refresh"]),
            "timed_refresh_immune_slices": [],
            "expanded_slices": {},
            "color_scheme": "",
            "label_colors": dict(spec.get("label_colors", {})),
            "shared_label_colors": {},
            "cross_filters_enabled": True,
            "native_filter_configuration": native_filters,
            "default_filters": "{}",
        },
        "version": VERSION,
    }


# ---------------------------------------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------------------------------------
def load_spec(path: Path) -> Spec:
    with path.open(encoding="utf-8") as fh:
        spec: Spec = yaml.safe_load(fh)
    return spec


def build_contents(spec: Spec) -> dict[str, str]:
    """Bundle file name (without the root folder) → YAML text, as Superset's importer expects."""

    def dump(data: Json) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)

    contents: dict[str, str] = {}
    contents["metadata.yaml"] = dump(
        {"version": VERSION, "type": "assets", "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()}
    )

    db_spec = copy.deepcopy(spec["database"])
    db_name = db_spec["name"]
    db_file = f"databases/{safe_name(db_name)}.yaml"
    contents[db_file] = dump(
        {
            "database_name": db_name,
            "sqlalchemy_uri": db_spec["sqlalchemy_uri"],
            "cache_timeout": db_spec.get("cache_timeout"),
            "expose_in_sqllab": bool(db_spec.get("expose_in_sqllab", True)),
            "allow_run_async": bool(db_spec.get("allow_run_async", False)),
            "allow_ctas": bool(db_spec.get("allow_ctas", False)),
            "allow_cvas": bool(db_spec.get("allow_cvas", False)),
            "allow_dml": bool(db_spec.get("allow_dml", False)),
            "allow_csv_upload": False,
            "extra": {
                "metadata_params": {},
                "engine_params": {"connect_args": {"application_name": "superset"}},
                "metadata_cache_timeout": {},
                "schemas_allowed_for_csv_upload": [],
            },
            "uuid": database_uuid(spec),
            "version": VERSION,
        }
    )

    for name, dataset in spec["datasets"].items():
        contents[f"datasets/{safe_name(db_name)}/{name}.yaml"] = dump(build_dataset(spec, name, dataset))

    chart_ids = {key: index for index, key in enumerate(spec["charts"], start=1)}
    for key, chart in spec["charts"].items():
        contents[f"charts/{safe_name(key)}_{chart_ids[key]}.yaml"] = dump(build_chart(spec, key, chart))

    used = {key for board in spec["dashboards"] for row in board["rows"] for key in row["charts"]}
    unused = set(spec["charts"]) - used
    if unused:
        raise SpecError(f"charts not placed on any dashboard: {sorted(unused)}")
    for board in spec["dashboards"]:
        contents[f"dashboards/{safe_name(board['slug'])}.yaml"] = dump(build_dashboard(spec, board, chart_ids))
    return contents


def database_file(spec: Spec) -> str:
    return f"databases/{safe_name(spec['database']['name'])}.yaml"


def write_zip(contents: dict[str, str], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(contents):
            info = zipfile.ZipInfo(f"{ROOT}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, contents[name])


def read_zip(path: Path) -> dict[str, str]:
    """Inverse of write_zip: strip the root folder like Superset's bundle loader does."""
    contents: dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            _, _, relative = name.partition("/")
            contents[relative] = zf.read(name).decode("utf-8")
    return contents


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, default=here / "spec.yaml")
    parser.add_argument("--out", type=Path, default=here / "gcc_bundle.zip", help="ZIP to write")
    parser.add_argument("--dir", type=Path, default=None, help="also write the files unzipped here")
    args = parser.parse_args(argv)

    contents = build_contents(load_spec(args.spec))
    write_zip(contents, args.out)
    if args.dir is not None:
        for name, text in contents.items():
            target = args.dir / ROOT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    counts = {
        kind: sum(1 for n in contents if n.startswith(f"{kind}/"))
        for kind in ("databases", "datasets", "charts", "dashboards")
    }
    print(f"wrote {args.out}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
