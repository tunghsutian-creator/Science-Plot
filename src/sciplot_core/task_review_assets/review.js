const notice = document.querySelector('#notice');
let noticeTimer;
function announce(message) {
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 4500);
}

const cards = [...document.querySelectorAll('[data-review-card]')];
const search = document.querySelector('#review-search');
const filter = document.querySelector('#review-filter');
function filterCards() {
  const query = search.value.trim().toLocaleLowerCase();
  let count = 0;
  for (const card of cards) {
    const matches = card.dataset.search.toLocaleLowerCase().includes(query);
    card.hidden = !matches || (filter.value === 'attention' && card.dataset.attention !== 'true');
    if (!card.hidden) count += 1;
  }
  document.querySelector('#filter-count').textContent = `显示 ${count} / ${cards.length} 张图形`;
  document.querySelector('#filter-empty').hidden = count > 0;
}
if (search) {
  search.addEventListener('input', filterCards);
  filter.addEventListener('change', filterCards);
  filterCards();
}

document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const field = document.getElementById(button.dataset.copy);
    try {
      await navigator.clipboard.writeText(field.value);
      announce('已复制，可粘贴到 AI 对话或文件管理器。');
    } catch {
      field.focus();
      field.select();
      announce('文本已选中，请按 ⌘C / Ctrl+C 复制。');
    }
  });
});

const dialog = document.querySelector('#image-dialog');
let imageOpener;
document.querySelectorAll('[data-zoom]').forEach(link => {
  link.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !dialog.showModal) return;
    event.preventDefault();
    imageOpener = link;
    const image = link.querySelector('img');
    document.querySelector('#large-image').src = image.src;
    document.querySelector('#large-image').alt = image.alt;
    document.querySelector('#image-title').textContent = image.alt;
    dialog.showModal();
  });
});
document.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => imageOpener?.focus());

const picker = document.querySelector('#candidate-picker');
const compareView = document.querySelector('#compare-view');
let compareOpener;
function showCandidate() {
  const option = picker.selectedOptions[0];
  const image = document.querySelector('#pair-image');
  const link = document.querySelector('#pair-link');
  image.src = option.dataset.image;
  image.alt = option.textContent;
  link.href = option.dataset.image;
  link.setAttribute('aria-label', `查看大图：${option.textContent}`);
  document.querySelector('#pair-label').textContent = option.textContent;
}
if (picker) {
  picker.addEventListener('change', showCandidate);
  document.querySelectorAll('[data-compare]').forEach(button => {
    button.addEventListener('click', () => {
      compareOpener = button;
      picker.value = button.dataset.compare;
      showCandidate();
      compareView.hidden = false;
      compareView.scrollIntoView({ block: 'start' });
      document.querySelector('#compare-title').focus({ preventScroll: true });
    });
  });
  document.querySelector('#close-compare').addEventListener('click', () => {
    compareView.hidden = true;
    compareOpener?.focus();
  });
}
