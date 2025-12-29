const catalogContent = document.getElementById("catalog-content");
const statusLine = document.getElementById("status");
const searchInput = document.getElementById("search");

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
  statusLine.textContent = "Showing 0 of 0 documents";
  catalogContent.innerHTML =
    "<div class=\"placeholder\">No documents match your search yet.</div>";
};

const updateStatus = (visibleCount, totalCount) => {
  statusLine.textContent = `Showing ${visibleCount} of ${totalCount} documents`;
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

const buildCard = (item) => {
  const card = document.createElement("article");
  card.className = "card";

  const title = document.createElement("h3");
  title.textContent = item.title;

  const summary = document.createElement("p");
  summary.textContent = item.summary;

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `
    <span><strong>Document type:</strong> ${item.doc_type_final}</span>
    <span><strong>Content type:</strong> ${item.content_type}</span>
    <span><strong>Page count:</strong> ${item.page_count}</span>
    <span><strong>Dataset:</strong> ${item.dataset}</span>
  `;

  const hasValidUrl = isValidUrl(item.doj_url);
  const link = document.createElement(hasValidUrl ? "a" : "span");
  link.className = "card-link";
  link.textContent = hasValidUrl ? "View original on DOJ" : "Source link pending";

  if (hasValidUrl) {
    link.href = item.doj_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  } else {
    link.classList.add("card-link--disabled");
    link.setAttribute("aria-disabled", "true");
    link.title = "The DOJ source link is not yet available for this entry.";
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

  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.appendChild(buildCard(item)));
  catalogContent.appendChild(fragment);
};

const filterItems = (query) => {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return catalogItems;
  }

  return catalogItems.filter((item) => {
    const title = item.title.toLowerCase();
    const summary = item.summary.toLowerCase();
    return title.includes(normalizedQuery) || summary.includes(normalizedQuery);
  });
};

const handleSearch = () => {
  const filtered = filterItems(searchInput.value);
  updateStatus(filtered.length, catalogItems.length);
  renderCatalog(filtered);
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

    updateStatus(catalogItems.length, catalogItems.length);
    renderCatalog(catalogItems);
  } catch (error) {
    showError();
  }
};

searchInput.addEventListener("input", handleSearch);

loadCatalog();
