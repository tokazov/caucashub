(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const state = {data: null, selectedOrderId: null, busy: false, attempt: null, generation: 0};
  const statuses = {pending: 'Ожидает оплаты', paid: 'Оплачен в тесте', failed: 'Отклонён', cancelled: 'Отменён', expired: 'Истёк', refunded: 'Возвращён в тесте'};
  const fulfillments = {not_started: 'Не выдана', granted: 'Выдана в тестовой базе', needs_review: 'Требуется разбор', revoked: 'Отозвана после возврата'};
  const dates = new Intl.DateTimeFormat('ru-RU', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tbilisi'});
  const price = (tetri, currency = 'GEL') => new Intl.NumberFormat('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(tetri) / 100) + (currency === 'GEL' ? ' ₾' : ' ' + currency);
  const date = value => {if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? '—' : dates.format(d);};
  const plural = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many;
  const duration = product => {const seconds = Number(product?.duration_seconds || 0); if (!seconds) return '—'; if (seconds >= 86400 && seconds % 86400 === 0 && product.kind !== 'boost') {const d = seconds / 86400; return d + ' ' + plural(d, 'день', 'дня', 'дней');} const h = seconds / 3600; return h + ' ' + plural(h, 'час', 'часа', 'часов');};
  const key = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(20)), n => n.toString(16).padStart(2, '0')).join('');
  function node(tag, text, className) {const el = document.createElement(tag); if (text !== undefined && text !== null) el.textContent = String(text); if (className) el.className = className; return el;}
  function showNotice(message, kind = 'info') {const el = byId('notice'); el.textContent = message; el.dataset.kind = kind; el.hidden = false; el.setAttribute('role', kind === 'error' ? 'alert' : 'status');}
  function errorMessage(error) {return error?.message || 'Не удалось связаться с тестовым сервером. Повторите запрос.';}
  async function request(path, options = {}) {
    const url = new URL(path, location.origin);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) throw new Error('Разрешены только запросы к локальной песочнице.');
    let response;
    try {response = await fetch(url.pathname + url.search, {credentials: 'same-origin', cache: 'no-store', ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});} catch (cause) {const error = new Error('Соединение прервалось. Результат запроса пока неизвестен.'); error.transport = true; throw error;}
    let body;
    try {body = await response.json();} catch {const error = new Error('Тестовый сервер вернул неожиданный ответ. Обновите состояние перед новой попыткой.'); error.status = response.status; error.uncertain = true; throw error;}
    if (!response.ok) {const detail = body.detail || body; const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? 'Проверьте выбранную услугу и поля запроса.' : detail.message || body.message || 'Тестовый запрос не выполнен.'; const error = new Error(message); error.status = response.status; error.code = detail.code || body.code; error.uncertain = response.status >= 500; throw error;}
    return body;
  }
  function setBusy(value) {state.busy = value; document.body.dataset.busy = String(value); syncControls();}
  function syncControls() {
    document.querySelectorAll('[data-busy-control]').forEach(el => {el.disabled = state.busy;});
    const product = selectedProduct();
    byId('start-session-button').hidden = !!state.data;
    byId('refresh-button').disabled = state.busy || !state.data;
    byId('product-select').disabled = state.busy || !state.data?.catalog?.length;
    byId('create-button').disabled = state.busy || !product?.enabled || (product.kind === 'boost' && !selectedTarget()?.eligible);
    document.querySelectorAll('[data-outcome],[data-order-id]').forEach(el => {el.disabled = state.busy;});
    byId('create-button').textContent = state.busy ? 'Подождите…' : state.attempt ? 'Повторить создание заказа' : 'Создать тестовый заказ';
    byId('retry-note').hidden = !state.attempt;
  }
  async function run(action) {if (state.busy) return; setBusy(true); try {await action();} catch (error) {if (error.status === 401) {state.data = null; state.attempt = null; state.selectedOrderId = null; render();} showNotice(errorMessage(error), 'error');} finally {setBusy(false);}}
  function selectedProduct() {return state.data?.catalog?.find(product => product.code === byId('product-select').value);}
  function selectedTarget() {return state.data?.targets?.find(target => target.id === byId('target-select').value);}
  function renderProducts() {
    const productSelect = byId('product-select'), targetSelect = byId('target-select');
    const productValue = productSelect.value, targetValue = targetSelect.value;
    productSelect.replaceChildren(); targetSelect.replaceChildren();
    for (const product of state.data?.catalog || []) {const option = node('option', product.title + (product.enabled ? ' · ' + price(product.price_tetri, product.currency) : ' — пока недоступно')); option.value = product.code; option.disabled = !product.enabled; productSelect.append(option);}
    if (Array.from(productSelect.options).some(option => option.value === productValue && !option.disabled)) productSelect.value = productValue;
    else {const first = Array.from(productSelect.options).find(option => !option.disabled); if (first) productSelect.value = first.value;}
    for (const target of (state.data?.targets || []).filter(item => item.eligible)) {const option = node('option', target.title + (target.eligible ? '' : ' — неактуален')); option.value = target.id; option.disabled = !target.eligible; targetSelect.append(option);}
    if (Array.from(targetSelect.options).some(option => option.value === targetValue && !option.disabled)) targetSelect.value = targetValue;
    else {const first = Array.from(targetSelect.options).find(option => !option.disabled); if (first) targetSelect.value = first.value;}
    if (!productSelect.options.length) {const option = node('option', 'Услуги проекта ещё не настроены'); option.value = ''; productSelect.append(option);}
    if (!targetSelect.options.length) {const option = node('option', 'Нет доступных демонстрационных грузов'); option.value = ''; targetSelect.append(option);}
    renderProductDetails();
  }
  function renderProductDetails() {
    const product = selectedProduct();
    byId('product-price').textContent = product ? price(product.price_tetri, product.currency) : '—';
    byId('product-duration').textContent = duration(product);
    byId('target-field').hidden = product?.kind !== 'boost';
    byId('product-note').textContent = product?.kind === 'boost' ? 'Тест проверяет принадлежность груза и срок продвижения. Место в настоящей выдаче не меняется.' : 'Тестовый Pro выдаётся на 30 дней. Раннее продление добавит период к действующему окончанию.';
    syncControls();
  }
  function badge(status, label) {const el = node('span', label, 'status'); el.dataset.status = status; return el;}
  function cell(row, label, content) {const td = node('td'); td.dataset.label = label; if (content instanceof Node) td.append(content); else td.textContent = String(content ?? '—'); row.append(td); return td;}
  function orderLabel(order) {const wrap = node('span', order.product_title || order.product_code); const detail = node('small', order.id, 'cell-detail'); wrap.append(detail); return wrap;}
  function renderOrders() {
    const rows = state.data?.orders || [], body = byId('orders-body'); body.replaceChildren();
    byId('orders-empty').hidden = !!rows.length; byId('orders-wrap').hidden = !rows.length;
    for (const order of rows) {const row = node('tr'); row.dataset.selected = String(order.id === state.selectedOrderId); cell(row, 'Услуга / заказ', orderLabel(order)); cell(row, 'Сумма', price(order.amount_tetri, order.currency)); cell(row, 'Статус', badge(order.status, statuses[order.status] || order.status)); cell(row, 'Создан', date(order.created_at)); const button = node('button', 'Выбрать', 'button secondary small'); button.type = 'button'; button.dataset.orderId = order.id; button.setAttribute('aria-label', 'Выбрать тестовый заказ ' + order.id); cell(row, 'Действие', button); body.append(row);}
  }
  function renderGrants() {
    const rows = state.data?.grants || [], body = byId('grants-body'); body.replaceChildren();
    byId('grants-empty').hidden = !!rows.length; byId('grants-wrap').hidden = !rows.length;
    for (const grant of rows) {const row = node('tr'); const revoked = !!(grant.revoked || grant.revoked_at); const upcoming = !revoked && !grant.active && new Date(grant.starts_at).getTime() > new Date(state.data.now).getTime(); const status = revoked ? 'revoked' : grant.active ? 'active' : upcoming ? 'pending' : 'expired'; const label = revoked ? 'Отозвана' : grant.active ? 'Действует' : upcoming ? 'Начнётся позже' : 'Истекла'; cell(row, 'Услуга', grant.product_title || (grant.kind === 'boost' ? 'Продвижение груза' : 'Подписка Pro')); cell(row, 'Объект', grant.target_id || 'Демоаккаунт'); cell(row, 'Начало', date(grant.starts_at)); cell(row, 'Окончание', date(grant.ends_at)); cell(row, 'Состояние', badge(status, label)); body.append(row);}
  }
  function renderCurrentOrder() {
    const order = state.data?.orders?.find(item => item.id === state.selectedOrderId);
    byId('order-empty').hidden = !!order; byId('current-order').hidden = !order;
    if (!order) return;
    byId('order-product').textContent = order.product_title || order.product_code;
    byId('order-status').textContent = statuses[order.status] || order.status; byId('order-status').dataset.status = order.status;
    byId('order-id').textContent = order.id; byId('order-amount').textContent = price(order.amount_tetri, order.currency); byId('order-created').textContent = date(order.created_at);
    byId('order-fulfillment').textContent = fulfillments[order.fulfillment_status] || order.fulfillment_status || '—';
    const grant = order.grant || state.data.grants?.find(item => item.order_id === order.id);
    byId('order-period-row').hidden = !grant; byId('order-period').textContent = grant ? date(grant.starts_at) + ' → ' + date(grant.ends_at) : '—';
    byId('fulfillment-warning').hidden = order.fulfillment_status !== 'needs_review';
    byId('fulfillment-warning').textContent = order.fulfillment_status === 'needs_review' ? 'Тестовая оплата подтверждена, но услуга не выдана. Нужен разбор или возврат. ' + (order.fulfillment_error || '') : '';
    const actions = byId('simulation-actions'); actions.replaceChildren();
    const addAction = (outcome, text, className) => {const button = node('button', text, 'button ' + className); button.type = 'button'; button.dataset.outcome = outcome; button.disabled = state.busy; actions.append(button);};
    if (order.status === 'pending') {addAction('paid', 'Успешная оплата', 'success'); addAction('failed', 'Банк отклонил', 'secondary'); addAction('cancelled', 'Пользователь отменил', 'secondary'); addAction('expired', 'Время оплаты истекло', 'secondary'); byId('simulation-note').textContent = 'Все кнопки имитируют результат. Карта и банковский аккаунт не нужны.';}
    else if (order.status === 'paid') {addAction('paid', 'Повторить подтверждение', 'secondary'); addAction('refunded', 'Полный тестовый возврат', 'danger'); byId('simulation-note').textContent = 'Повтор подтверждения не должен продлить доступ второй раз. Возврат доступен для последнего платежа этой услуги; при наличии более позднего продления сервер объяснит ограничение.';}
    else byId('simulation-note').textContent = 'Это завершённый тестовый заказ. Для следующей попытки создайте новый заказ в форме слева.';
  }
  function render() {
    byId('customer-select').value = state.data?.customer?.id || byId('customer-select').value;
    byId('server-time').textContent = state.data?.now ? 'Серверное время: ' + date(state.data.now) + ' · Тбилиси' : 'Состояние тестового сервера ещё не получено.';
    renderProducts(); renderOrders(); renderGrants(); renderCurrentOrder(); syncControls();
  }
  async function loadState() {
    const generation = state.generation; const data = await request('/api/state');
    if (generation !== state.generation) return;
    state.data = data;
    if (!data.orders?.some(order => order.id === state.selectedOrderId)) state.selectedOrderId = data.orders?.[0]?.id || null;
    render();
  }
  async function chooseCustomer(customerId) {
    state.generation++; state.attempt = null; state.selectedOrderId = null; state.data = null; render();
    await request('/api/session', {method: 'POST', body: JSON.stringify({customer_id: customerId})});
    await loadState(); showNotice('Выбран демонстрационный аккаунт. Данные рабочего сайта не используются.');
  }
  byId('customer-select').addEventListener('change', event => {if (state.data) run(() => chooseCustomer(event.target.value));});
  byId('start-session-button').addEventListener('click', () => run(() => chooseCustomer(byId('customer-select').value)));
  byId('refresh-button').addEventListener('click', () => run(async () => {await loadState(); showNotice('Тестовое состояние обновлено.');}));
  for (const id of ['product-select', 'target-select']) byId(id).addEventListener('change', () => {state.attempt = null; renderProductDetails();});
  byId('checkout-form').addEventListener('submit', event => {event.preventDefault(); run(async () => {
    const product = selectedProduct(); if (!product?.enabled) return;
    const body = {product_code: product.code}; if (product.kind === 'boost') {const target = selectedTarget(); if (!target?.eligible) throw new Error('Выберите свой актуальный демонстрационный груз.'); body.target_id = target.id;}
    const fingerprint = JSON.stringify(body);
    if (!state.attempt || state.attempt.fingerprint !== fingerprint) state.attempt = {key: key(), fingerprint, body};
    let result;
    try {result = await request('/api/orders', {method: 'POST', headers: {'Idempotency-Key': state.attempt.key}, body: JSON.stringify(state.attempt.body)});} catch (error) {if (!error.transport && !error.uncertain) state.attempt = null; throw error;}
    const order = result.order || result; state.selectedOrderId = order.id; await loadState(); state.attempt = null; showNotice('Тестовый заказ создан. Теперь можно проверить ответ имитатора банка.', 'success');
  });});
  byId('orders-body').addEventListener('click', event => {const button = event.target.closest('[data-order-id]'); if (!button || state.busy) return; state.selectedOrderId = button.dataset.orderId; byId('orders-body').querySelectorAll('tr').forEach(row => {row.dataset.selected = String(row.querySelector('[data-order-id]')?.dataset.orderId === state.selectedOrderId);}); renderCurrentOrder(); syncControls();});
  byId('simulation-actions').addEventListener('click', event => {const button = event.target.closest('[data-outcome]'); if (!button || state.busy || !state.selectedOrderId) return; const outcome = button.dataset.outcome; run(async () => {
    await request('/api/orders/' + encodeURIComponent(state.selectedOrderId) + '/simulate', {method: 'POST', body: JSON.stringify({outcome})});
    await loadState(); const order = state.data.orders.find(item => item.id === state.selectedOrderId);
    showNotice(order?.fulfillment_status === 'needs_review' ? 'Ответ имитатора сохранён. Оплата требует разбора; повторно оплачивать не нужно.' : outcome === 'refunded' ? 'Тестовый возврат обработан. Реальные деньги не перемещались.' : outcome === 'paid' ? 'Подтверждение обработано. Проверьте срок услуги: повтор не добавляет новый период.' : 'Тестовый результат сохранён: ' + (statuses[outcome] || outcome) + '.', order?.fulfillment_status === 'needs_review' ? 'info' : 'success');
  });});
  run(async () => {try {await loadState();} catch (error) {if (error.status !== 401) throw error; render(); showNotice('Выберите демонстрационный аккаунт и нажмите «Открыть демоаккаунт». Это не вход в рабочий сайт.');}});
})();
