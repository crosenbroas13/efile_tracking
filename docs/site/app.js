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
const formatPct = (numerator, denominator) => {
  if (!denominator || denominator <= 0) {
    return "0%";
  }
  return `${Math.round((numerator / denominator) * 100)}%`;
};

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

const formatPageCount = (value) => {
  const pages = Number(value || 0);
  if (!Number.isFinite(pages) || pages <= 0) {
    return "n/a";
  }
  return formatNumber(pages);
};

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

const buildChartList = (items, total) => {
  const chart = document.createElement("div");
  chart.className = "chart-list";
  items.forEach(({ label, count }) => {
    const row = document.createElement("div");
    row.className = "chart-row";

    const labelEl = document.createElement("span");
    labelEl.className = "chart-label";
    labelEl.textContent = label;

    const barTrack = document.createElement("span");
    barTrack.className = "chart-bar-track";

    const barFill = document.createElement("span");
    barFill.className = "chart-bar-fill";
    const ratio = total ? count / total : 0;
    barFill.style.width = `${Math.max(ratio * 100, 1)}%`;

    barTrack.appendChild(barFill);

    const valueEl = document.createElement("span");
    valueEl.className = "chart-value";
    valueEl.textContent = `${formatNumber(count)} (${Math.round(ratio * 100)}%)`;

    row.append(labelEl, barTrack, valueEl);
    chart.appendChild(row);
  });
  return chart;
};

const buildChartSection = ({ title, items, total }) => {
  const wrapper = document.createElement("div");
  wrapper.className = "chart-section";

  const heading = document.createElement("h4");
  heading.textContent = title;
  wrapper.appendChild(heading);

  wrapper.appendChild(buildChartList(items, total));
  return wrapper;
};

const buildBreakdownCard = ({ title, description, metrics, list, charts }) => {
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

  if (charts?.length) {
    charts.forEach((chart) => card.appendChild(chart));
  }

  return card;
};

const buildDocumentCard = (item) => {
  const card = document.createElement("article");
  card.className = "card";

  const title = document.createElement("h3");
  title.textContent = item.title || "Untitled document";

  const summary = document.createElement("p");
  summary.textContent =
    item.summary ||
    "This entry is listed in the public catalog so reviewers can trace it back to the DOJ source.";

  const fileType = formatExtension(item.extension);
  const fileSize = formatBytes(item.size_bytes);
  const pageCount = formatPageCount(item.page_count);

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `
    <span><strong>VOL folder:</strong> ${item.dataset || "Unknown VOL"}</span>
    <span><strong>File type:</strong> ${fileType}</span>
    <span><strong>File size:</strong> ${fileSize}</span>
    <span><strong>Pages:</strong> ${pageCount}</span>
    <span><strong>Document type:</strong> ${item.doc_type_final || "Unknown"}</span>
    <span><strong>Content type:</strong> ${item.content_type || "Unknown"}</span>
    <span><strong>Relative path:</strong> ${item.rel_path || "Unavailable"}</span>
  `;

  const hasValidLink = isValidUrl(item.doj_url);
  const link = document.createElement(hasValidLink ? "a" : "span");
  link.className = `card-link${hasValidLink ? "" : " card-link--disabled"}`;
  link.textContent = hasValidLink ? "Open DOJ source" : "Source link pending";
  if (hasValidLink) {
    link.href = item.doj_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }

  card.append(title, summary, meta, link);
  return card;
};

const renderCatalog = (items) => {
  catalogContent.innerHTML = "";

  if (items.length === 0) {
    showPlaceholder();
    return;
  }

  const totalDocuments = items.length;
  const totalBytes = items.reduce((sum, item) => {
    const sizeBytes = Number.parseFloat(item.size_bytes);
    return sum + (Number.isFinite(sizeBytes) ? sizeBytes : 0);
  }, 0);
  const datasetCounts = countBy(items, "dataset");
  const extensionCounts = countBy(items, "extension", "(none)");
  const mimeCounts = countBy(items, "detected_mime");
  const validLinks = items.filter((item) => isValidUrl(item.doj_url)).length;
  const pendingLinks = totalDocuments - validLinks;
  const coveragePct = totalDocuments
    ? `${Math.round((validLinks / totalDocuments) * 100)}%`
    : "0%";
  const textBasedDocs = items.filter((item) => item.classification === "Text-based");
  const verifiedGood = textBasedDocs.filter((item) => item.text_quality_label === "GOOD");
  const suspiciousText = textBasedDocs.filter((item) =>
    ["EMPTY", "LOW"].includes(item.text_quality_label)
  );
  const textBasedShare = formatPct(textBasedDocs.length, totalDocuments);
  const verifiedShare = formatPct(verifiedGood.length, textBasedDocs.length);
  const suspiciousShare = formatPct(suspiciousText.length, textBasedDocs.length);
  const hasTextSignals = items.some((item) => item.classification || item.text_quality_label);

  const grid = document.createElement("div");
  grid.className = "breakdown-grid";

  grid.append(
    buildBreakdownCard({
      title: "Executive summary",
      description:
        "Quick totals that explain the overall size of the public catalog without opening any files.",
      metrics: [
        { label: "Total documents", value: formatNumber(totalDocuments) },
        { label: "Total size", value: formatBytes(totalBytes) },
        { label: "VOL folders represented", value: formatNumber(datasetCounts.length) },
      ],
    }),
    buildBreakdownCard({
      title: "VOL folder structure",
      description:
        "Highlights every VOL folder represented in the catalog so reviewers can confirm nothing is missing.",
      list: datasetCounts,
      charts: [
        buildChartSection({
          title: "Documents by VOL folder",
          items: datasetCounts,
          total: totalDocuments,
        }),
      ],
    }),
    buildBreakdownCard({
      title: "Files by type",
      description:
        "Shows the mix of file extensions and detected MIME types so reviewers can spot non-PDF formats.",
      list: [
        ...extensionCounts.map((item) => ({
          label: `Extension: ${formatExtension(item.label)}`,
          count: item.count,
        })),
        ...mimeCounts.map((item) => ({
          label: `MIME type: ${item.label}`,
          count: item.count,
        })),
      ],
      charts: [
        buildChartSection({
          title: "File extensions",
          items: extensionCounts.slice(0, 12),
          total: totalDocuments,
        }),
        buildChartSection({
          title: "Detected MIME types",
          items: mimeCounts.slice(0, 12),
          total: totalDocuments,
        }),
      ],
    }),
    ...(hasTextSignals
      ? [
          buildBreakdownCard({
            title: "Text-based PDF readiness",
            description:
              "Highlights which PDFs are truly text-ready, using probe and text scan signals when available.",
            metrics: [
              {
                label: "Text-based PDFs",
                value: `${formatNumber(textBasedDocs.length)} (${textBasedShare})`,
              },
              {
                label: "Verified good text (GOOD)",
                value: `${formatNumber(verifiedGood.length)} (${verifiedShare})`,
              },
              {
                label: "Suspicious text (EMPTY/LOW)",
                value: `${formatNumber(suspiciousText.length)} (${suspiciousShare})`,
              },
            ],
            charts: [
              buildChartSection({
                title: "PDF text readiness",
                items: [
                  { label: "Text-based PDFs", count: textBasedDocs.length },
                  { label: "Verified GOOD text", count: verifiedGood.length },
                  { label: "Suspicious text", count: suspiciousText.length },
                ],
                total: totalDocuments,
              }),
            ],
          }),
        ]
      : []),
    buildBreakdownCard({
      title: "Source link readiness",
      description:
        "Counts how many entries are ready to open on justice.gov versus still waiting on a source URL.",
      metrics: [
        { label: "Valid DOJ links", value: formatNumber(validLinks) },
        { label: "Links pending", value: formatNumber(pendingLinks) },
        { label: "Coverage", value: coveragePct },
      ],
      charts: [
        buildChartSection({
          title: "Source link coverage",
          items: [
            { label: "Valid DOJ links", count: validLinks },
            { label: "Links pending", count: pendingLinks },
          ],
          total: totalDocuments,
        }),
      ],
    })
  );

  const documentSection = document.createElement("section");
  documentSection.className = "document-section";

  const documentHeading = document.createElement("h3");
  documentHeading.textContent = "Document catalog (all published files)";

  const documentIntro = document.createElement("p");
  documentIntro.textContent =
    "Every entry below is part of the public index, with plain-language context so non-technical reviewers can confirm what each file is and whether the DOJ source link is ready.";

  const documentGrid = document.createElement("div");
  documentGrid.className = "document-grid";
  items.forEach((item) => documentGrid.appendChild(buildDocumentCard(item)));

  documentSection.append(documentHeading, documentIntro, documentGrid);

  catalogContent.append(grid, documentSection);
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
