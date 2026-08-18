const TENDER_CATEGORIES = [
  { key: 'all', label: 'All' },
  { key: 'goods', label: 'Goods' },
  { key: 'works', label: 'Works' },
  { key: 'consultancy', label: 'Consultancy' },
  { key: 'non_consultancy', label: 'Non Consultancy' }
];

let allTenders = Array.isArray(window.PUBLIC_TENDERS) ? window.PUBLIC_TENDERS : [];
let activeCategory = 'all';

function getCategoryCounts(tenders) {
  const counts = { all: tenders.length, goods: 0, works: 0, consultancy: 0, non_consultancy: 0 };
  tenders.forEach((tender) => {
    if (counts[tender.category] !== undefined) {
      counts[tender.category] += 1;
    }
  });
  return counts;
}

function renderFilters(counts) {
  const container = document.getElementById('tenderFilters');
  if (!container) return;

  container.innerHTML = TENDER_CATEGORIES.map((cat) => `
    <button class="filter-pill ${cat.key === activeCategory ? 'active' : ''}" data-category="${cat.key}">
      ${cat.label}
      <span class="count">${counts[cat.key] ?? 0}</span>
    </button>
  `).join('');

  container.querySelectorAll('.filter-pill').forEach((button) => {
    button.addEventListener('click', () => {
      activeCategory = button.dataset.category;
      renderFilters(getCategoryCounts(allTenders));
      renderTenders();
    });
  });
}

function tenderCardHtml(tender) {
  const logo = tender.logoUrl
    ? `<img class="tender-logo" src="${tender.logoUrl}" alt="${tender.entity}" onerror="this.outerHTML='<div class=\'tender-logo fallback\'>${(tender.entity || '?').charAt(0)}</div>'">`
    : `<div class="tender-logo fallback">${(tender.entity || '?').charAt(0)}</div>`;

  const tags = (tender.tags || [])
    .map((tag) => `<span class="tag tag-${tag.style || 'neutral'}">${tag.label}</span>`)
    .join('');

  return `
    <div class="tender-card" data-id="${tender.id}">
      ${logo}
      <div class="tender-body">
        <div class="tender-title">${tender.title}</div>
        <span class="tender-entity">${tender.entity}</span>
        <div class="tender-meta">
          <span>Invitation Date: <b>${tender.invitationDate}</b></span>
          <span>Submission Deadline: <span class="deadline">${tender.submissionDeadline}</span></span>
          <span>Number: <b>${tender.number}</b></span>
        </div>
        <div class="tender-tags">${tags}</div>
      </div>
      <div class="tender-action">
        <a href="${tender.detailsUrl || '#'}" class="view-details-btn">View Details</a>
      </div>
    </div>
  `;
}

function renderTenders() {
  const listEl = document.getElementById('tendersList');
  const emptyEl = document.getElementById('tendersEmpty');
  if (!listEl || !emptyEl) return;

  const filtered = activeCategory === 'all'
    ? allTenders
    : allTenders.filter((tender) => tender.category === activeCategory);

  if (filtered.length === 0) {
    listEl.innerHTML = '';
    emptyEl.style.display = 'block';
    return;
  }

  emptyEl.style.display = 'none';
  listEl.innerHTML = filtered.map(tenderCardHtml).join('');
}

function initTendersSection() {
  const loadingEl = document.getElementById('tendersLoading');
  if (!loadingEl) return;

  if (!allTenders.length) {
    loadingEl.textContent = 'No tenders available at the moment.';
    renderFilters(getCategoryCounts(allTenders));
    renderTenders();
    return;
  }

  loadingEl.remove();
  renderFilters(getCategoryCounts(allTenders));
  renderTenders();
}

document.addEventListener('DOMContentLoaded', initTendersSection);
