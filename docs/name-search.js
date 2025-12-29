const INDEX_URL = "data/public_name_index.json";

const elements = {
  input: document.getElementById("name-query"),
  clearButton: document.getElementById("clear-search"),
  status: document.getElementById("index-status"),
  feedback: document.getElementById("search-feedback"),
  results: document.getElementById("results"),
};

const state = {
  items: [],
  meta: null,
  ready: false,
};

const normalizeInput = (value) => {
  if (!value) return "";
  return value.trim().replace(/\s+/g, " ").toLowerCase();
};

const normalizeNoComma = (value) => {
  if (!value) return "";
  return value.replace(/,/g, " ").replace(/\s+/g, " ").trim();
};

const deriveCanonicalKey = (normalizedValue) => {
  if (!normalizedValue) return null;

  if (normalizedValue.includes(",")) {
    const parts = normalizedValue.split(",");
    if (parts.length < 2) return null;
    const lastName = parts[0].trim();
    const firstName = parts.slice(1).join(",").trim();
    const firstToken = firstName.split(" ").filter(Boolean)[0];
    if (lastName && firstToken) {
      return `${lastName}|${firstToken}`;
    }
    return null;
  }

  const tokens = normalizeNoComma(normalizedValue)
    .split(" ")
    .filter(Boolean);

  if (tokens.length === 2) {
    return `${tokens[1]}|${tokens[0]}`;
  }

  return null;
};

const uniqueSortedPages = (hits) => {
  const pages = new Set();
  hits.forEach((hit) => pages.add(hit.page));
  return Array.from(pages).sort((a, b) => a - b);
};

const formatHitSummary = (hits) => {
  const sorted = [...hits].sort((a, b) => a.page - b.page);
  return sorted.map((hit) => `p. ${hit.page} (${hit.count})`).join(", ");
};

const setFeedback = (message, tone = "placeholder") => {
  elements.feedback.className = `search-feedback ${tone}`;
  elements.feedback.textContent = message;
};

const clearResults = () => {
  elements.results.innerHTML = "";
};

const renderResults = (matches, query) => {
  clearResults();

  if (!state.ready) {
    return;
  }

  if (!query) {
    setFeedback(
      "Enter a person name to see matching documents.",
      "placeholder",
    );
    return;
  }

  if (matches.length === 0) {
    setFeedback(
      "No results. Try last, first formatting, remove middle initials, or search by last name only.",
      "placeholder",
    );
    return;
  }

  setFeedback(
    `Showing ${matches.length} result${matches.length === 1 ? "" : "s"}.`,
    "success",
  );

  matches.forEach((item, index) => {
    const section = document.createElement("section");
    section.className = "name-result";

    const header = document.createElement("div");
    header.className = "name-result__header";

    const title = document.createElement("h3");
    title.textContent = item.display_name;

    const summary = document.createElement("p");
    summary.className = "name-result__summary";
    summary.textContent = `${item.docs.length} document${
      item.docs.length === 1 ? "" : "s"
    } matched.`;

    header.appendChild(title);
    header.appendChild(summary);

    const tableWrap = document.createElement("div");
    tableWrap.className = "table-wrap";

    const table = document.createElement("table");
    table.className = "results-table";

    const thead = document.createElement("thead");
    thead.innerHTML = `
      <tr>
        <th scope="col">Dataset</th>
        <th scope="col">Document</th>
        <th scope="col">Pages</th>
        <th scope="col">Total mentions</th>
        <th scope="col">DOJ Link</th>
        <th scope="col">Details</th>
      </tr>
    `;

    const tbody = document.createElement("tbody");

    item.docs.forEach((doc, docIndex) => {
      const pages = uniqueSortedPages(doc.hits).join(", ");
      const detailId = `detail-${index}-${docIndex}`;

      const row = document.createElement("tr");
      row.className = "doc-row";
      row.dataset.detailId = detailId;
      row.innerHTML = `
        <td>${doc.dataset}</td>
        <td>${doc.title}</td>
        <td>${pages || "—"}</td>
        <td>${doc.total_count}</td>
        <td>
          <a
            href="${doc.doj_url}"
            target="_blank"
            rel="noopener noreferrer"
            class="link-primary"
          >
            View on DOJ
          </a>
        </td>
        <td>
          <button class="btn-tertiary toggle-details" type="button" aria-expanded="false">
            Details
          </button>
        </td>
      `;

      const detailRow = document.createElement("tr");
      detailRow.id = detailId;
      detailRow.className = "doc-details";
      detailRow.hidden = true;
      detailRow.innerHTML = `
        <td colspan="6">
          <div class="doc-details__content">
            <p class="doc-details__text">
              ${formatHitSummary(doc.hits)}
            </p>
            <a
              href="${doc.doj_url}"
              target="_blank"
              rel="noopener noreferrer"
              class="link-primary"
            >
              View on DOJ
            </a>
          </div>
        </td>
      `;

      tbody.appendChild(row);
      tbody.appendChild(detailRow);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);

    table.addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (link) return;

      const button = event.target.closest(".toggle-details");
      const row = event.target.closest(".doc-row");
      if (!row) return;

      if (button || row) {
        const detailRow = table.querySelector(`#${row.dataset.detailId}`);
        if (!detailRow) return;
        const toggleButton = row.querySelector(".toggle-details");
        const isHidden = detailRow.hidden;
        detailRow.hidden = !isHidden;
        if (toggleButton) {
          toggleButton.setAttribute("aria-expanded", String(isHidden));
          toggleButton.textContent = isHidden ? "Hide" : "Details";
        }
      }
    });

    section.appendChild(header);
    section.appendChild(tableWrap);
    elements.results.appendChild(section);
  });
};

const findMatches = (query) => {
  const normalized = normalizeInput(query);
  const normalizedNoComma = normalizeNoComma(normalized);

  if (!normalizedNoComma) return [];

  const canonicalKey = deriveCanonicalKey(normalized);
  if (canonicalKey) {
    const canonicalMatches = state.items.filter(
      (item) => item.canonical_key === canonicalKey,
    );
    if (canonicalMatches.length > 0) return canonicalMatches;
  }

  const variantMatches = state.items.filter((item) =>
    item.variants.includes(normalizedNoComma),
  );
  if (variantMatches.length > 0) return variantMatches;

  return state.items.filter((item) =>
    item.display_name.toLowerCase().includes(normalizedNoComma),
  );
};

const handleSearch = () => {
  const query = elements.input.value;
  const matches = findMatches(query);
  renderResults(matches, normalizeInput(query));
};

const setReadyState = () => {
  const { meta } = state;
  if (meta) {
    elements.status.textContent = `Index updated ${meta.last_updated} • ${meta.item_count} names`;
  } else {
    elements.status.textContent = "Name index loaded.";
  }
  state.ready = true;
  handleSearch();
};

const setErrorState = () => {
  elements.status.textContent = "Name index not available.";
  setFeedback(
    "The public name index is not yet published. Please check back soon.",
    "error",
  );
  elements.input.disabled = true;
  elements.clearButton.disabled = true;
};

const loadIndex = async () => {
  setFeedback("Loading name index…", "placeholder");
  try {
    const response = await fetch(INDEX_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Failed to load index");
    }
    const data = await response.json();
    state.items = Array.isArray(data.items) ? data.items : [];
    state.meta = data.meta || null;
    setReadyState();
  } catch (error) {
    setErrorState();
  }
};

if (elements.input) {
  elements.input.addEventListener("input", handleSearch);
}

if (elements.clearButton) {
  elements.clearButton.addEventListener("click", () => {
    elements.input.value = "";
    elements.input.focus();
    handleSearch();
  });
}

loadIndex();
