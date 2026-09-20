// SciPlot review interactions. The saved native document remains the authority.
const $ = selector => document.querySelector(selector);
const notice = $('#notice');
let noticeTimer;
function announce(message) {
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 4500);
}
async function copyText(field) {
  try {
    await navigator.clipboard.writeText(field.value);
    announce('已复制，可粘贴到 AI 对话或文件管理器。');
  } catch {
    field.hidden = false;
    field.focus();
    field.select();
    announce('文本已选中，请按 ⌘C / Ctrl+C 复制。');
  }
}

const cards = [...document.querySelectorAll('[data-review-card]')];
const search = $('#review-search');
const filter = $('#review-filter');
const gallery = $('#gallery-view');
const workbench = $('#workspace-view');
const inspector = $('#inspector');
const detailButton = $('#details-toggle');
const inspectorContent = $('#inspector-content');
const rail = $('#rail-list');
const viewport = $('#canvas-viewport');
const canvasImage = $('#canvas-image');
const canvasEmpty = $('#canvas-empty');
const drafts = new Map();
let selectedCard;
let currentMode = 'workspace';
let zoom = 1;
let pan = { x: 0, y: 0 };
let drag;
let fitMode = true;
let imageReady = false;
const visibleCards = () => cards.filter(card => !card.hidden);
const titleOf = card => card.dataset.title || card.querySelector('h2')?.textContent || '图形';
const toolbar = search?.closest('.toolbar');
const toolbarHome = document.createComment('gallery toolbar');
if (toolbar) toolbar.before(toolbarHome);

function editText(section) {
  const instruction = section.querySelector('[data-edit-instruction]').value.trim();
  const output = section.querySelector('[data-edit-output]');
  output.value = instruction ? `${section.querySelector('[data-edit-template]').value}\n\n修改要求：\n${instruction}` : '';
  section.querySelector('[data-copy-edit]').disabled = !instruction;
  return output;
}
document.addEventListener('input', event => {
  if (!event.target.matches('[data-edit-instruction]')) return;
  const section = event.target.closest('[data-edit-request]');
  const card = event.target.closest('[data-review-card]') || selectedCard;
  drafts.set(card, event.target.value);
  editText(section);
});
document.addEventListener('click', event => {
  const copy = event.target.closest('[data-copy]');
  if (copy) copyText(document.getElementById(copy.dataset.copy));
  const edit = event.target.closest('[data-copy-edit]');
  if (edit && !edit.disabled) copyText(editText(edit.closest('[data-edit-request]')));
});

function paintView() {
  canvasImage.style.transform = `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
  $('#zoom-level').textContent = imageReady ? `${Math.round(zoom * 100)}%` : '—';
}
function fitImage() {
  if (!imageReady || !viewport.clientWidth || !viewport.clientHeight) return;
  zoom = Math.min((viewport.clientWidth - 48) / canvasImage.naturalWidth,
    (viewport.clientHeight - 48) / canvasImage.naturalHeight, 1);
  zoom = Math.max(0.01, zoom);
  pan = { x: 0, y: 0 };
  fitMode = true;
  paintView();
}
function changeZoom(factor) {
  if (!imageReady) return;
  zoom = Math.max(0.01, Math.min(4, zoom * factor));
  fitMode = false;
  paintView();
}
function setImageReady(ready) {
  imageReady = ready;
  for (const id of ['zoom-in', 'zoom-out', 'zoom-fit']) $(`#${id}`).disabled = !ready;
  canvasImage.hidden = !ready;
  canvasEmpty.hidden = ready;
}
canvasImage.addEventListener('load', () => {
  setImageReady(true);
  canvasImage.style.width = `${canvasImage.naturalWidth}px`;
  canvasImage.style.height = `${canvasImage.naturalHeight}px`;
  fitImage();
});
canvasImage.addEventListener('error', () => {
  setImageReady(false);
  canvasEmpty.textContent = '预览无法读取。请让 AI 重新查询项目。';
  paintView();
});
$('#zoom-in').addEventListener('click', () => changeZoom(1.25));
$('#zoom-out').addEventListener('click', () => changeZoom(1 / 1.25));
$('#zoom-fit').addEventListener('click', fitImage);
viewport.addEventListener('pointerdown', event => {
  if (!imageReady || event.button !== 0) return;
  drag = { x: event.clientX, y: event.clientY, startX: pan.x, startY: pan.y };
  viewport.setPointerCapture(event.pointerId);
  viewport.classList.add('is-dragging');
  viewport.focus({ preventScroll: true });
});
viewport.addEventListener('pointermove', event => {
  if (!drag) return;
  pan = { x: drag.startX + event.clientX - drag.x, y: drag.startY + event.clientY - drag.y };
  fitMode = false;
  paintView();
});
function endDrag() { drag = undefined; viewport.classList.remove('is-dragging'); }
viewport.addEventListener('pointerup', endDrag);
viewport.addEventListener('pointercancel', endDrag);
viewport.addEventListener('lostpointercapture', endDrag);
viewport.addEventListener('dblclick', fitImage);
// Ordinary wheel scrolling remains page navigation; zoom only with an explicit modifier.
viewport.addEventListener('wheel', event => {
  if (!(event.ctrlKey || event.metaKey) || !imageReady) return;
  event.preventDefault();
  changeZoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
}, { passive: false });
viewport.addEventListener('keydown', event => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (['+', '=', '-', '0'].includes(event.key)) {
    event.preventDefault();
    if (event.key === '0') fitImage();
    else changeZoom(event.key === '-' ? 1 / 1.25 : 1.25);
  }
  if (imageReady && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault();
    const step = event.shiftKey ? 100 : 30;
    if (event.key === 'ArrowLeft') pan.x -= step;
    if (event.key === 'ArrowRight') pan.x += step;
    if (event.key === 'ArrowUp') pan.y -= step;
    if (event.key === 'ArrowDown') pan.y += step;
    fitMode = false;
    paintView();
  }
});
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => { if (fitMode) fitImage(); }).observe(viewport);
}
function showDetails(show) {
  inspector.hidden = !show;
  workbench.classList.toggle('details-hidden', !show);
  detailButton.setAttribute('aria-expanded', String(show));
  if (fitMode) requestAnimationFrame(fitImage);
}
detailButton.addEventListener('click', () => showDetails(inspector.hidden));
showDetails(!matchMedia('(max-width: 1000px)').matches);

function renderInspector(card) {
  inspectorContent.replaceChildren();
  if (!card) return;
  const clone = card.cloneNode(true);
  const taskState = clone.querySelector('header .badge');
  if (taskState && clone.querySelector('.tags')) clone.querySelector('.tags').append(taskState);
  clone.querySelectorAll(':scope > header, :scope > .image').forEach(node => node.remove());
  const common = gallery.querySelector('[data-comparison-state]');
  if (common) clone.prepend(common.cloneNode(true));
  // Cloned copy fields must never point at hidden fields in the gallery.
  clone.querySelectorAll('[id]').forEach(node => { node.id = `active-${node.id}`; });
  clone.querySelectorAll('[data-copy]').forEach(node => { node.dataset.copy = `active-${node.dataset.copy}`; });
  clone.querySelectorAll('[for]').forEach(node => { node.htmlFor = `active-${node.htmlFor}`; });
  inspectorContent.append(...clone.childNodes);
  const editor = inspectorContent.querySelector('[data-edit-request]');
  if (editor) {
    editor.querySelector('[data-edit-instruction]').value = drafts.get(card) || '';
    editText(editor);
  }
}
function selectCard(card, focus = false) {
  selectedCard = card;
  const shown = visibleCards();
  const index = shown.indexOf(card);
  rail.querySelectorAll('[data-card-index]').forEach(button => {
    const active = cards[Number(button.dataset.cardIndex)] === card;
    button.setAttribute('aria-pressed', String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) { button.focus(); button.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
  });
  $('#canvas-title').textContent = card ? titleOf(card) : '没有匹配的图形';
  $('#canvas-caption').textContent = card && card.dataset.subtitle !== titleOf(card) ? card.dataset.subtitle || '' : '';
  $('#canvas-position').textContent = card ? `${index + 1} / ${shown.length}` : '0 张图形';
  $('#figure-prev').disabled = index <= 0;
  $('#figure-next').disabled = index < 0 || index >= shown.length - 1;
  renderInspector(card);
  setImageReady(false);
  canvasImage.removeAttribute('src');
  canvasImage.alt = card ? titleOf(card) : '';
  const source = card?.querySelector('a.image img');
  canvasEmpty.textContent = source ? '正在读取预览…' : card ? '此图暂无可用预览，详情中保留当前状态。' : '请更换搜索词或显示全部图形。';
  if (source) canvasImage.src = source.src;
  paintView();
}
function stepFigure(step, focus = false) {
  const shown = visibleCards();
  const next = shown.indexOf(selectedCard) + step;
  if (next >= 0 && next < shown.length) selectCard(shown[next], focus);
}
$('#figure-prev').addEventListener('click', () => stepFigure(-1));
$('#figure-next').addEventListener('click', () => stepFigure(1));
rail.addEventListener('keydown', event => {
  const keys = ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const shown = visibleCards();
  if (event.key === 'Home') selectCard(shown[0], true);
  else if (event.key === 'End') selectCard(shown.at(-1), true);
  else stepFigure(['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1, true);
});
function refreshRail() {
  rail.replaceChildren();
  const shown = visibleCards();
  $('#rail-count').textContent = `${shown.length} 张`;
  for (const card of shown) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'figure-row';
    button.dataset.cardIndex = cards.indexOf(card);
    const preview = card.querySelector('a.image img');
    if (preview) {
      const thumb = preview.cloneNode();
      thumb.className = 'figure-thumb'; thumb.alt = ''; button.append(thumb);
    }
    const info = document.createElement('span'); info.className = 'figure-info';
    const title = document.createElement('span'); title.className = 'figure-name'; title.textContent = titleOf(card);
    const subtitle = document.createElement('span'); subtitle.className = 'figure-subtitle'; subtitle.textContent = card.dataset.subtitle || '';
    const state = document.createElement('span'); state.className = 'figure-state';
    state.textContent = [...new Set([card.querySelector('.tags .badge')?.textContent,
      card.querySelector('header .badge')?.textContent].filter(Boolean))].join(' · ');
    state.classList.toggle('attention', card.dataset.attention === 'true');
    info.append(title);
    if (subtitle.textContent && subtitle.textContent !== title.textContent && subtitle.textContent !== state.textContent) info.append(subtitle);
    if (state.textContent && state.textContent !== title.textContent) info.append(state);
    button.append(info);
    button.addEventListener('click', () => selectCard(card)); rail.append(button);
  }
  selectCard(shown.includes(selectedCard) ? selectedCard : shown[0]);
}
function filterCards() {
  const query = search?.value.trim().toLocaleLowerCase() || '';
  for (const card of cards) card.hidden = !(card.dataset.search || '').toLocaleLowerCase().includes(query)
    || (filter?.value === 'attention' && card.dataset.attention !== 'true');
  const count = visibleCards().length;
  if ($('#filter-count')) $('#filter-count').textContent = `显示 ${count} / ${cards.length} 张图形`;
  if ($('#filter-empty')) $('#filter-empty').hidden = count > 0;
  refreshRail();
}
search?.addEventListener('input', filterCards);
filter?.addEventListener('change', filterCards);
function setMode(mode) {
  currentMode = mode;
  workbench.hidden = mode !== 'workspace'; gallery.hidden = mode === 'workspace';
  if (toolbar) {
    if (mode === 'workspace') $('#rail-filter').append(toolbar);
    else toolbarHome.after(toolbar);
  }
  document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === mode)));
  if (mode === 'workspace') { renderInspector(selectedCard); fitMode = true; requestAnimationFrame(fitImage); }
  else gallery.querySelectorAll('[data-edit-request]').forEach(section => {
    section.querySelector('[data-edit-instruction]').value = drafts.get(section.closest('[data-review-card]')) || '';
    editText(section);
  });
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.view)));

const dialog = $('#image-dialog');
let imageOpener;
document.addEventListener('click', event => {
  const link = event.target.closest('[data-zoom]');
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !dialog.showModal) return;
  event.preventDefault(); imageOpener = link;
  const image = link.querySelector('img');
  if (!image?.getAttribute('src')) return;
  $('#large-image').src = image.src; $('#large-image').alt = image.alt;
  $('#image-title').textContent = image.alt; dialog.showModal();
});
$('[data-close-dialog]').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => imageOpener?.focus());
const about = $('#about-dialog');
$('[data-about]').addEventListener('click', () => about.showModal());
$('[data-close-about]').addEventListener('click', () => about.close());

const picker = $('#candidate-picker');
const compareView = $('#compare-view');
let compareOpener;
function showCandidate() {
  const option = picker.selectedOptions[0];
  $('#pair-image').src = option.dataset.image; $('#pair-image').alt = option.textContent;
  $('#pair-link').href = option.dataset.image;
  $('#pair-link').setAttribute('aria-label', `查看大图：${option.textContent}`);
  $('#pair-label').textContent = option.textContent;
}
if (picker) {
  picker.addEventListener('change', showCandidate);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-compare]');
    if (!button) return;
    compareOpener = button; picker.value = button.dataset.compare;
    showCandidate(); setMode('gallery'); compareView.hidden = false;
    compareView.scrollIntoView({ block: 'start' }); $('#compare-title').focus({ preventScroll: true });
  });
  $('#close-compare').addEventListener('click', () => {
    compareView.hidden = true;
    if (compareOpener?.closest('#inspector')) {
      setMode('workspace');
      [...inspectorContent.querySelectorAll('[data-compare]')]
        .find(button => button.dataset.compare === compareOpener.dataset.compare)?.focus();
    } else compareOpener?.focus();
  });
}
// Enhancement only changes presentation. No request writes or renderer calls exist here.
if (cards.length) {
  document.body.classList.add('workspace-ready'); $('#view-switch').hidden = false;
  setMode(currentMode); filterCards();
}
