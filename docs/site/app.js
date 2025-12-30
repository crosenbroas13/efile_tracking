const catalogContent = document.getElementById("catalog-content");
const runSummaryStatus = document.getElementById("run-summary-status");
const runSummaryMetrics = document.getElementById("run-summary-metrics");
const catalogTitle = document.getElementById("catalog");
const runSummaryTitle = document.getElementById("run-summary-title");

let catalogItems = [];
const FETCH_TIMEOUT_MS = 12000;
const LOADING_HINT_MS = 3500;

const showLoading = () => {
  if (catalogContent) {
    catalogContent.innerHTML = "<div class=\"loading\">Loading…</div>";
  }
  if (runSummaryStatus) {
    runSummaryStatus.textContent = "Loading inventory details…";
  }
  if (runSummaryMetrics) {
    runSummaryMetrics.innerHTML = "";
  }
};

const showError = () => {
  if (catalogContent) {
    catalogContent.innerHTML =
      "<div class=\"error\">The catalog is not yet published. Please check back soon.</div>";
  }
  if (runSummaryStatus) {
    runSummaryStatus.textContent = "Latest inventory details unavailable.";
  }
  if (runSummaryMetrics) {
    runSummaryMetrics.innerHTML = "";
  }
};

const showPlaceholder = () => {
  if (catalogContent) {
    catalogContent.innerHTML =
      "<div class=\"placeholder\">No catalog data is available yet. Check back after the next publish cycle.</div>";
  }
  if (runSummaryStatus) {
    runSummaryStatus.textContent = "Latest inventory details unavailable.";
  }
  if (runSummaryMetrics) {
    runSummaryMetrics.innerHTML = "";
  }
};

const showTimeout = () => {
  if (catalogContent) {
    catalogContent.innerHTML =
      "<div class=\"error\">The catalog is taking longer than expected to load. Please refresh or try again soon.</div>";
  }
  if (runSummaryStatus) {
    runSummaryStatus.textContent = "Inventory details are still loading. Please refresh or try again soon.";
  }
  if (runSummaryMetrics) {
    runSummaryMetrics.innerHTML = "";
  }
};

const formatNumber = (value) => Number(value || 0).toLocaleString("en-US");

const formatBytes = (value) => {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / 1024 ** exponent;
  const precision = exponent === 0 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[exponent]}`;
};

const formatExtension = (value) => {
  if (!value) {
    return "(none)";
  }
  const normalized = String(value).trim();
  if (!normalized || normalized === "(none)") {
    return "(none)";
  }
  return normalized.replace(".", "").toUpperCase();
};

const extractDataPullDate = (meta = {}) => {
  const inventoryMeta = meta.inventory || {};
  const runId = inventoryMeta.run_id || meta.inventory_run_id || "";
  const sourceRoot = inventoryMeta.source_root_name || meta.source_root_name || "";
  const labelSource = runId || sourceRoot || "";
  if (!labelSource) {
    return null;
  }
  const match = labelSource.match(/(\d{4}[._-]\d{2}[._-]\d{2}|\d{2}[._-]\d{2}[._-]\d{2})/);
  return match ? match[0] : null;
};

const updateCatalogTitles = (meta = {}) => {
  const dateLabel = extractDataPullDate(meta);
  if (catalogTitle) {
    catalogTitle.textContent = dateLabel ? `Catalog breakdown — ${dateLabel}` : "Catalog breakdown";
  }
  if (runSummaryTitle) {
    runSummaryTitle.textContent = dateLabel ? `Latest inventory run — ${dateLabel}` : "Latest inventory run";
  }
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

const buildCountList = (items) => {
  const list = document.createElement("ul");
  list.className = "breakdown-list";
  items.forEach(({ label, count }) => {
    const item = document.createElement("li");
    item.innerHTML = `<span>${label}</span><strong>${formatNumber(count)}</strong>`;
    list.appendChild(item);
  });
  return list;
};

const countVolFolders = (items) => {
  const datasetSet = new Set();
  const volSet = new Set();
  items.forEach((item) => {
    const dataset = item.dataset ? String(item.dataset) : "";
    if (!dataset) {
      return;
    }
    datasetSet.add(dataset);
    if (dataset.toUpperCase().startsWith("VOL")) {
      volSet.add(dataset);
    }
  });
  return {
    totalDatasets: datasetSet.size,
    volFolders: volSet.size,
  };
};

const renderInventorySummary = (meta = {}, items = []) => {
  if (!runSummaryStatus || !runSummaryMetrics) {
    return;
  }

  const inventoryMeta = meta.inventory || {};
  const totals = inventoryMeta.totals || {};
  const folderCounts = countVolFolders(items);
  const inventoryRunId = inventoryMeta.run_id || meta.inventory_run_id;
  const inventorySource = inventoryMeta.source_root_name || meta.source_root_name;
  const resolvedFolderCount =
    folderCounts.volFolders || Number(inventoryMeta.folder_count) || folderCounts.totalDatasets;

  const metrics = [];

  if (inventoryRunId) {
    metrics.push({ label: "Inventory run ID", value: inventoryRunId });
  }
  if (inventorySource) {
    metrics.push({ label: "DataPull folder", value: inventorySource });
  }
  if (Number.isFinite(Number(totals.files))) {
    metrics.push({ label: "Inventory files", value: formatNumber(totals.files) });
  }
  if (Number.isFinite(Number(totals.total_bytes))) {
    metrics.push({ label: "Inventory size", value: formatBytes(totals.total_bytes) });
  }
  if (Number.isFinite(Number(resolvedFolderCount))) {
    metrics.push({ label: "VOL folders", value: formatNumber(resolvedFolderCount) });
  }

  runSummaryMetrics.innerHTML = "";

  if (metrics.length === 0) {
    runSummaryStatus.textContent = "Latest inventory details are not yet published.";
    return;
  }

  runSummaryStatus.textContent = "Showing totals from the latest full inventory run.";
  runSummaryMetrics.appendChild(buildMetricList(metrics));
};

const buildDatasetTypeBreakdown = (items) => {
  const datasetMap = new Map();

  items.forEach((item) => {
    const dataset = item.dataset ? String(item.dataset) : "Unknown VOL";
    const extension = formatExtension(item.extension);
    if (!datasetMap.has(dataset)) {
      datasetMap.set(dataset, new Map());
    }
    const extMap = datasetMap.get(dataset);
    extMap.set(extension, (extMap.get(extension) || 0) + 1);
  });

  const datasetEntries = Array.from(datasetMap.entries())
    .map(([dataset, extMap]) => {
      const typeCounts = Array.from(extMap.entries())
        .map(([label, count]) => ({ label, count }))
        .sort((a, b) => b.count - a.count);
      const total = typeCounts.reduce((sum, item) => sum + item.count, 0);
      return { dataset, total, typeCounts };
    })
    .sort((a, b) => a.dataset.localeCompare(b.dataset));

  const wrapper = document.createElement("div");
  wrapper.className = "dataset-breakdown";

  datasetEntries.forEach(({ dataset, total, typeCounts }) => {
    const section = document.createElement("section");
    section.className = "dataset-breakdown__section";

    const heading = document.createElement("h4");
    heading.textContent = `${dataset} (${formatNumber(total)} files)`;

    section.append(heading, buildCountList(typeCounts));
    wrapper.appendChild(section);
  });

  return wrapper;
};

const renderCatalog = (items, meta = {}) => {
  if (!catalogContent) {
    return;
  }

  catalogContent.innerHTML = "";

  if (items.length === 0) {
    showPlaceholder();
    return;
  }

  updateCatalogTitles(meta);

  const breakdownIntro = document.createElement("p");
  breakdownIntro.textContent =
    "Each DataSet (VOL) is listed with the total number of files by type so non-technical reviewers can confirm every folder was captured.";

  const breakdown = buildDatasetTypeBreakdown(items);

  catalogContent.append(breakdownIntro, breakdown);
};

const loadCatalog = async () => {
  showLoading();
  let loadingHintTimer;
  let timeoutId;
  const controller = new AbortController();

  try {
    loadingHintTimer = setTimeout(() => {
      if (runSummaryStatus) {
        runSummaryStatus.textContent = "Still loading inventory details. Thanks for your patience.";
      }
    }, LOADING_HINT_MS);
    timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const response = await fetch("data/public_index.json", {
      cache: "default",
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error("Catalog not found");
    }

    const data = await response.json();
    catalogItems = Array.isArray(data.items) ? data.items : [];

    renderInventorySummary(data.meta || {}, catalogItems);
    renderCatalog(catalogItems, data.meta || {});
  } catch (error) {
    if (error && error.name === "AbortError") {
      showTimeout();
    } else {
      showError();
    }
  } finally {
    clearTimeout(loadingHintTimer);
    clearTimeout(timeoutId);
  }
};

loadCatalog();
