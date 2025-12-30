const catalogContent = document.getElementById("catalog-content");
const statusLine = document.getElementById("status");

let catalogItems = [];

const showLoading = () => {
  statusLine.textContent = "Loading…";
  catalogContent.innerHTML = "<div class=\"loading\">Loading…</div>";
};

const showError = () => {
  statusLine.textContent = "Catalog unavailable";
  catalogContent.innerHTML =
    "<div class=\"error\">The catalog is not yet published. Please check back soon.</div>";
};

const showPlaceholder = () => {
  statusLine.textContent = "No published documents yet";
  catalogContent.innerHTML =
    "<div class=\"placeholder\">No catalog data is available yet. Check back after the next publish cycle.</div>";
};

const updateStatus = (totalCount) => {
  statusLine.textContent = `Snapshot of ${totalCount} documents`;
};

const isValidUrl = (value) => {
  if (!value) {
    return false;
  }

  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (error) {
    return false;
  }
};

const formatNumber = (value) => Number(value || 0).toLocaleString("en-US");

const countBy = (items, key, fallback = "Unknown") => {
  const counts = new Map();
  items.forEach((item) => {
    const label = item[key] ? String(item[key]) : fallback;
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count);
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

const buildBreakdownCard = ({ title, description, metrics, list }) => {
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

  if (list?.length) {
    card.appendChild(buildCountList(list));
  }

  return card;
};

const renderCatalog = (items) => {
  catalogContent.innerHTML = "";

  if (items.length === 0) {
    showPlaceholder();
    return;
  }

  const totalDocuments = items.length;
  const totalPages = items.reduce((sum, item) => {
    const pageCount = Number.parseInt(item.page_count, 10);
    return sum + (Number.isFinite(pageCount) ? pageCount : 0);
  }, 0);
  const datasetCounts = countBy(items, "dataset");
  const docTypeCounts = countBy(items, "doc_type_final");
  const contentTypeCounts = countBy(items, "content_type");
  const validLinks = items.filter((item) => isValidUrl(item.doj_url)).length;
  const pendingLinks = totalDocuments - validLinks;
  const coveragePct = totalDocuments
    ? `${Math.round((validLinks / totalDocuments) * 100)}%`
    : "0%";

  const grid = document.createElement("div");
  grid.className = "breakdown-grid";

  grid.append(
    buildBreakdownCard({
      title: "Executive summary",
      description:
        "Quick totals that explain the overall size of the public catalog without opening any files.",
      metrics: [
        { label: "Total documents", value: formatNumber(totalDocuments) },
        { label: "Total pages", value: formatNumber(totalPages) },
        { label: "Datasets represented", value: formatNumber(datasetCounts.length) },
      ],
    }),
    buildBreakdownCard({
      title: "Dataset structure",
      description:
        "Highlights which datasets contribute the most documents so non-technical reviewers can see where the volume sits.",
      list: datasetCounts.slice(0, 5),
    }),
    buildBreakdownCard({
      title: "Files by type",
      description:
        "Shows the mix of document and content types to indicate what kinds of files dominate the catalog.",
      list: [
        ...docTypeCounts.slice(0, 4).map((item) => ({
          label: `Document type: ${item.label}`,
          count: item.count,
        })),
        ...contentTypeCounts.slice(0, 4).map((item) => ({
          label: `Content type: ${item.label}`,
          count: item.count,
        })),
      ],
    }),
    buildBreakdownCard({
      title: "Source link readiness",
      description:
        "Counts how many entries are ready to open on justice.gov versus still waiting on a source URL.",
      metrics: [
        { label: "Valid DOJ links", value: formatNumber(validLinks) },
        { label: "Links pending", value: formatNumber(pendingLinks) },
        { label: "Coverage", value: coveragePct },
      ],
    })
  );

  catalogContent.appendChild(grid);
};

const loadCatalog = async () => {
  showLoading();

  try {
    const response = await fetch("data/public_index.json", {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error("Catalog not found");
    }

    const data = await response.json();
    catalogItems = Array.isArray(data.items) ? data.items : [];

    // Future enhancements hook:
    // - Doc-type filters
    // - Content-type filters
    // - Name/entity search
    // - Summary charts
    // - Additional pages (about, methodology)

    updateStatus(catalogItems.length);
    renderCatalog(catalogItems);
  } catch (error) {
    showError();
  }
};

loadCatalog();
