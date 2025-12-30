const deltaContent = document.getElementById("delta-content");
const statusLine = document.getElementById("status");

const showLoading = () => {
  statusLine.textContent = "Loading…";
  deltaContent.innerHTML = "<div class=\"loading\">Loading…</div>";
};

const showError = () => {
  statusLine.textContent = "Run summary unavailable";
  deltaContent.innerHTML =
    "<div class=\"error\">The run comparison data is not yet published. Please check back soon.</div>";
};

const showPlaceholder = () => {
  statusLine.textContent = "No run comparison data";
  deltaContent.innerHTML =
    "<div class=\"placeholder\">No comparison data is available yet. Publish an inventory/probe delta to enable this view.</div>";
};

const formatNumber = (value) => Number(value || 0).toLocaleString("en-US");

const formatBytes = (value) => {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const normalized = bytes / 1024 ** exponent;
  return `${normalized.toFixed(normalized >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
};

const buildMetricList = (metrics) => {
  const list = document.createElement("dl");
  list.className = "breakdown-metrics";
  metrics.forEach(({ label, value }) => {
    const item = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    item.append(dt, dd);
    list.appendChild(item);
  });
  return list;
};

const buildBreakdownCard = ({ title, description, metrics }) => {
  const card = document.createElement("article");
  card.className = "breakdown-card";

  const heading = document.createElement("h3");
  heading.textContent = title;

  const body = document.createElement("p");
  body.textContent = description;

  card.append(heading, body);

  if (metrics?.length) {
    card.appendChild(buildMetricList(metrics));
  }

  return card;
};

const buildTable = ({ title, description, columns, rows }) => {
  const wrapper = document.createElement("section");
  wrapper.className = "document-section";

  const heading = document.createElement("h3");
  heading.textContent = title;

  const intro = document.createElement("p");
  intro.textContent = description;

  const tableWrap = document.createElement("div");
  tableWrap.className = "table-wrap";

  const table = document.createElement("table");
  table.className = "results-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.label;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column.key];
      td.textContent = value ?? "—";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  table.append(thead, tbody);
  tableWrap.appendChild(table);
  wrapper.append(heading, intro, tableWrap);
  return wrapper;
};

const buildDeltaRows = (items, fields, formatters = {}) =>
  items.map((item) => ({
    name: item.name,
    first: formatters.first ? formatters.first(item[fields.first]) : formatNumber(item[fields.first]),
    last: formatters.last ? formatters.last(item[fields.last]) : formatNumber(item[fields.last]),
    delta: formatters.delta ? formatters.delta(item[fields.delta]) : formatNumber(item[fields.delta]),
  }));

const renderDelta = (data) => {
  deltaContent.innerHTML = "";

  const inventory = data?.inventory;
  const probe = data?.probe;
  const meta = data?.meta || {};

  if (!inventory || !probe) {
    showPlaceholder();
    return;
  }

  statusLine.textContent = `Updated ${meta.last_updated || "recently"}`;

  const inventoryTotals = inventory.totals || {};
  const probeTotals = probe.totals || {};

  const grid = document.createElement("div");
  grid.className = "breakdown-grid";

  grid.append(
    buildBreakdownCard({
      title: "Inventory change summary",
      description:
        "Shows how many files and total storage shifted between the first and latest inventory pull.",
      metrics: [
        {
          label: "First inventory (files)",
          value: formatNumber(inventoryTotals.first?.file_count),
        },
        {
          label: "Latest inventory (files)",
          value: formatNumber(inventoryTotals.last?.file_count),
        },
        {
          label: "Change (files)",
          value: formatNumber(inventoryTotals.delta?.file_count),
        },
        {
          label: "Change (total size)",
          value: formatBytes(inventoryTotals.delta?.total_size_bytes),
        },
      ],
    }),
    buildBreakdownCard({
      title: "Probe change summary",
      description:
        "Highlights how the number of PDFs analyzed and text-ready documents shifted between the first and latest probe run.",
      metrics: [
        {
          label: "First probe (PDFs)",
          value: formatNumber(probeTotals.first?.pdf_count),
        },
        {
          label: "Latest probe (PDFs)",
          value: formatNumber(probeTotals.last?.pdf_count),
        },
        {
          label: "Change (PDFs)",
          value: formatNumber(probeTotals.delta?.pdf_count),
        },
        {
          label: "Change (text-ready PDFs)",
          value: formatNumber(probeTotals.delta?.text_ready_count),
        },
      ],
    }),
    buildBreakdownCard({
      title: "Run metadata",
      description:
        "Records which runs were compared so reviewers know exactly which pull is represented.",
      metrics: [
        {
          label: "First inventory run",
          value: meta.inventory?.first_run_id || "—",
        },
        {
          label: "Latest inventory run",
          value: meta.inventory?.last_run_id || "—",
        },
        {
          label: "First probe run",
          value: meta.probe?.first_run_id || "—",
        },
        {
          label: "Latest probe run",
          value: meta.probe?.last_run_id || "—",
        },
      ],
    })
  );

  const inventoryCountRows = buildDeltaRows(
    inventory.top_levels || [],
    {
      first: "first_count",
      last: "last_count",
      delta: "delta_count",
    },
    {
      delta: (value) => (value > 0 ? `+${formatNumber(value)}` : formatNumber(value)),
    }
  );

  const inventorySizeRows = buildDeltaRows(
    inventory.top_levels || [],
    {
      first: "first_size_bytes",
      last: "last_size_bytes",
      delta: "delta_size_bytes",
    },
    {
      first: formatBytes,
      last: formatBytes,
      delta: (value) => (value > 0 ? `+${formatBytes(value)}` : formatBytes(value)),
    }
  );

  const probePdfRows = buildDeltaRows(
    probe.top_levels || [],
    {
      first: "first_pdf_count",
      last: "last_pdf_count",
      delta: "delta_pdf_count",
    },
    {
      delta: (value) => (value > 0 ? `+${formatNumber(value)}` : formatNumber(value)),
    }
  );

  const probeTextRows = buildDeltaRows(
    probe.top_levels || [],
    {
      first: "first_text_ready_count",
      last: "last_text_ready_count",
      delta: "delta_text_ready_count",
    },
    {
      delta: (value) => (value > 0 ? `+${formatNumber(value)}` : formatNumber(value)),
    }
  );

  deltaContent.append(
    grid,
    buildTable({
      title: "Inventory file counts by top-level folder",
      description:
        "Use this table to confirm which top folders gained or lost files between the first and latest inventory pull.",
      columns: [
        { key: "name", label: "Top-level folder" },
        { key: "first", label: "First pull" },
        { key: "last", label: "Latest pull" },
        { key: "delta", label: "Change" },
      ],
      rows: inventoryCountRows,
    }),
    buildTable({
      title: "Inventory storage size by top-level folder",
      description:
        "Shows how storage volume changed, which helps explain whether growth is due to more files or larger files.",
      columns: [
        { key: "name", label: "Top-level folder" },
        { key: "first", label: "First pull" },
        { key: "last", label: "Latest pull" },
        { key: "delta", label: "Change" },
      ],
      rows: inventorySizeRows,
    }),
    buildTable({
      title: "Probe PDFs by top-level folder",
      description:
        "Shows how many PDFs were probed in each top-level folder during the first and latest runs.",
      columns: [
        { key: "name", label: "Top-level folder" },
        { key: "first", label: "First probe" },
        { key: "last", label: "Latest probe" },
        { key: "delta", label: "Change" },
      ],
      rows: probePdfRows,
    }),
    buildTable({
      title: "Text-ready PDFs by top-level folder",
      description:
        "Highlights where readable, searchable PDFs increased or dropped between probe runs.",
      columns: [
        { key: "name", label: "Top-level folder" },
        { key: "first", label: "First probe" },
        { key: "last", label: "Latest probe" },
        { key: "delta", label: "Change" },
      ],
      rows: probeTextRows,
    })
  );
};

const loadDelta = async () => {
  showLoading();

  try {
    const response = await fetch("data/inventory_probe_delta.json", {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error("Delta data not found");
    }

    const data = await response.json();
    renderDelta(data);
  } catch (error) {
    showError();
  }
};

loadDelta();
