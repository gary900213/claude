// 刷卡自動記帳：Gmail 刷卡通知（推薦）、iPhone 捷徑 + Gist、文字檔匯入、補記、測試解析。
import {
  forgetMerchant, generateGmailScript, getInbox, getLearned, getPending, importFileText, removePending,
  saveGistId, saveGmailUrl, syncAll,
} from '../services/inbox.js';
import { listCategories } from '../services/categories.js';
import { formatAmount, todayStr } from '../domain/format.js';
import { guessCategory, parseInboxItem } from '../domain/inbox.js';
import { goBack } from '../router.js';
import { setPrefill } from './edit.js';
import { catMap, confirmDialog, esc, subHeader, toast } from './components.js';

const TEMPLATE = '{"amount":"〔金額〕","merchant":"〔商家〕","time":"〔目前日期〕"}';

export async function render(el) {
  const inbox0 = await getInbox();
  el.innerHTML = `
    ${subHeader('刷卡自動記帳')}

    <section class="card">
      <div class="section-head"><h2>狀態</h2>
        <button class="btn small primary" type="button" data-act="sync">立即同步</button></div>
      <ul class="status-list" data-status></ul>
      <p class="hint">打開記帳本、或從背景切回來時會自動同步。</p>
    </section>

    <section class="card" data-pending-card hidden>
      <div class="section-head"><h2>待補金額</h2></div>
      <p class="hint">這些交易沒有讀到台幣金額（例如外幣消費、捷徑沒帶到金額），點「補記」填上金額就好。</p>
      <ul class="tx-list" data-pending></ul>
    </section>

    <section class="card guide">
      <div class="section-head"><h2>方法一：Gmail 刷卡通知 <span class="badge">推薦</span></h2></div>
      <p>網購、實體刷卡、Apple Pay 全部抓得到，<b>不用設定 iPhone 捷徑</b>。Google 會在雲端幫你讀刷卡通知信，只要設定一次。</p>
      <details class="steps" ${inbox0.gmailUrl ? '' : 'open'}>
        <summary>${inbox0.gmailUrl ? '已設定，點這裡重新設定' : '開始設定（約 3 分鐘）'}</summary>
        <ol>
          <li>在銀行 App 或網銀開啟「<b>Email 刷卡通知</b>」，寄到你的 Gmail。</li>
          <li>
            銀行通知信的寄件人（選填，建議填，只會讀這些寄件人的信；不填就找主旨有「刷卡、消費、交易」的信）：
            <input id="gmail-senders" class="text-input" autocomplete="off" placeholder="例如 notice@bank.com.tw"
                   value="${esc(inbox0.gmailSenders ?? '')}">
            <button class="btn block" type="button" data-act="gen">產生並複製程式碼</button>
            <textarea id="gmail-code" class="code-area" readonly rows="4" hidden aria-label="程式碼"></textarea>
          </li>
          <li>用收通知的 Gmail 帳號打開 <span class="mono">script.google.com</span> →「<b>新專案</b>」，刪掉原本的內容，貼上程式碼，按儲存。</li>
          <li>上方函式選單選 <span class="mono">authorize</span> →「<b>執行</b>」，依指示允許讀取 Gmail。看到「Google 尚未驗證這個應用程式」時，點「進階」→「前往」；這是你自己的程式，只有你能執行。</li>
          <li>右上「<b>部署</b>」→「新增部署作業」→ 類型選「<b>網頁應用程式</b>」：執行身分「<b>我</b>」、誰可以存取「<b>所有人</b>」→ 部署，複製「網頁應用程式網址」（結尾是 <span class="mono">/exec</span>）。</li>
          <li>
            貼到這裡：
            <form data-gmail-form novalidate>
              <input id="gmail-url" class="text-input" inputmode="url" autocomplete="off"
                     placeholder="https://script.google.com/macros/s/…/exec" value="${esc(inbox0.gmailUrl ?? '')}">
              <button class="btn block primary" type="submit">儲存並測試</button>
            </form>
          </li>
        </ol>
        <p>「所有人」的意思是：拿到這個網址和程式裡的密鑰才能讀，而且只讀得到符合條件的刷卡通知信開頭，讀不到你其他的信。網址不要給別人。</p>
      </details>
    </section>

    <section class="card">
      <div class="section-head"><h2>測試：貼一則刷卡通知</h2></div>
      <p class="hint">把銀行的刷卡簡訊或 Email 內容貼進來，看看記帳本會怎麼記（不會真的記帳）。</p>
      <textarea id="notice-test" class="code-area" rows="3" placeholder="例如：您的信用卡於11/17在全家消費NT$85"></textarea>
      <button class="btn block" type="button" data-act="test">看看會怎麼記</button>
      <p class="test-result" data-test-result aria-live="polite"></p>
    </section>

    <section class="card guide">
      <div class="section-head"><h2>方法二：iPhone 捷徑</h2></div>
      <p>銀行只發<b>簡訊</b>通知，或想在 Apple Pay <b>感應付款</b>時就記帳，用這個方法。需要 GitHub 帳號。</p>
      <details class="steps">
        <summary>展開設定步驟</summary>
        <form class="gist-form" data-gist-form novalidate>
          <label class="field">
            <span>收件匣（GitHub Gist 網址）</span>
            <input id="gist-url" name="gist" class="text-input" inputmode="url" autocomplete="off" placeholder="https://gist.github.com/…"
                   value="${inbox0.gistId ? `https://gist.github.com/${esc(inbox0.gistId)}` : ''}">
          </label>
          <button class="btn block" type="submit">儲存</button>
        </form>
        <h3>1. 建立收件匣</h3>
        <ol>
          <li>電腦打開 <span class="mono">gist.github.com</span>，登入 GitHub。</li>
          <li>檔名填 <span class="mono">ledger.txt</span>，內容隨便打一個字，按「Create <b>secret</b> gist」。</li>
          <li>把網址貼到上面，按儲存。</li>
        </ol>
        <h3>2. 建立 GitHub 權杖</h3>
        <ol>
          <li>GitHub 的 Settings → Developer settings → Personal access tokens → <b>Fine-grained tokens</b> → Generate new token。</li>
          <li>Account permissions 只把 <b>Gists</b> 設成 <b>Read and write</b>，產生後複製 <span class="mono">github_pat_…</span>。</li>
        </ol>
        <h3>3. 建立捷徑（之後兩種自動化共用）</h3>
        <ol>
          <li>「捷徑」App → 新增捷徑，命名「記帳收件匣」，加入動作「<b>取得 URL 內容</b>」，網址：
            <div class="copy-box"><code data-copy-src data-api-url>https://api.github.com/gists/〔Gist ID〕/comments</code><button class="btn small" type="button" data-copy>複製</button></div>
            方法 <b>POST</b>；標頭 <span class="mono">Authorization</span> 值 <span class="mono">Bearer 〔你的權杖〕</span>；要求本文選 <b>JSON</b>，欄位 <span class="mono">body</span>（文字）值選「<b>捷徑輸入</b>」。
          </li>
        </ol>
        <h3>4. 設定自動化（選一種，不要同時開，否則實體感應會記兩次）</h3>
        <ol>
          <li><b>刷卡簡訊</b>：自動化 →「＋」→「<b>訊息</b>」，寄件人選銀行 →「立即執行」→ 執行「記帳收件匣」。網購、實體刷卡都抓得到。</li>
          <li><b>Apple Pay 感應</b>：自動化 →「＋」→「<b>交易</b>」，勾選卡片 →「立即執行」→ 先加「文字」動作貼上
            <div class="copy-box"><code data-copy-src>${esc(TEMPLATE)}</code><button class="btn small" type="button" data-copy>複製</button></div>
            把〔金額〕〔商家〕換成「捷徑輸入」的金額、商家，〔目前日期〕換成「目前日期」（格式自訂 <span class="mono">yyyy-MM-dd HH:mm</span>），再執行「記帳收件匣」並把「文字」傳給它。只有實體感應會觸發。</li>
        </ol>
        <h3>不想用 GitHub？</h3>
        <p>捷徑改用「<b>附加到文字檔</b>」存到 iCloud 雲碟，要記帳時在這裡選檔案匯入（已匯入過的不會重複記）：</p>
        <div class="btn-row">
          <label class="btn">選擇檔案<input type="file" accept=".txt,.json,text/plain,application/json" data-act="file" hidden></label>
        </div>
        <p>Secret gist 不會被搜尋到，但<b>知道網址的人看得到</b>內容，不要分享出去。權杖只放在捷徑裡，記帳本不會存。</p>
      </details>
    </section>

    <section class="card" data-learned-card hidden>
      <div class="section-head"><h2>記住的商店分類</h2></div>
      <p class="hint">改過自動記帳紀錄的類別後，同一家店（含其他分店）之後會自動用這個類別。</p>
      <ul class="cat-rows" data-learned></ul>
    </section>`;

  const statusEl = el.querySelector('[data-status]');

  async function paint() {
    const [inbox, pending, learned, cats] = await Promise.all([
      getInbox(), getPending(), getLearned(), listCategories({ includeHidden: true }),
    ]);
    const map = catMap(cats);
    el.querySelector('[data-api-url]').textContent =
      `https://api.github.com/gists/${inbox.gistId || '〔Gist ID〕'}/comments`;

    const line = (name, configured, error) =>
      `<li><span>${name}</span><span class="${error ? 'error' : configured ? 'ok' : 'muted'}">${
        error ? `失敗：${esc(error)}` : configured ? '已連接' : '未設定'
      }</span></li>`;
    statusEl.innerHTML =
      line('Gmail 刷卡通知', Boolean(inbox.gmailUrl), inbox.gmailUrl && inbox.gmailError) +
      line('iPhone 捷徑（Gist）', Boolean(inbox.gistId), inbox.gistId && inbox.lastError) +
      (inbox.lastSyncAt ? `<li><span>上次同步</span><span class="muted">${new Date(inbox.lastSyncAt).toLocaleString('zh-TW')}</span></li>` : '');

    el.querySelector('[data-pending-card]').hidden = !pending.length;
    el.querySelector('[data-pending]').innerHTML = pending
      .map(
        (p) => `
        <li class="pending-row">
          <span class="tx-main"><span class="tx-cat">${esc(p.merchant || '刷卡消費')}</span>
            <span class="tx-note">${esc(p.date ?? '日期不明')}</span></span>
          <button class="btn small" type="button" data-fill="${esc(p.key)}">補記</button>
          <button class="icon-btn" type="button" data-drop="${esc(p.key)}" aria-label="略過這筆">×</button>
        </li>`,
      )
      .join('');

    const entries = Object.entries(learned);
    el.querySelector('[data-learned-card]').hidden = !entries.length;
    el.querySelector('[data-learned]').innerHTML = entries
      .map(([key, id]) => {
        const c = map.get(id);
        return `
        <li class="cat-row">
          <span class="cat-icon" aria-hidden="true">${esc(c?.icon ?? '❔')}</span>
          <span class="cat-row-name">${esc(key)}<small>→ ${esc(c?.name ?? '已刪除的類別')}</small></span>
          <button class="btn small" type="button" data-forget="${esc(key)}">移除</button>
        </li>`;
      })
      .join('');
    return { inbox, learned, cats };
  }

  const describe = (r) => {
    const parts = [];
    if (r.added) parts.push(`記入 ${r.added} 筆`);
    if (r.pending) parts.push(`${r.pending} 筆待補金額`);
    return parts.length ? `已同步：${parts.join('，')}` : '已同步，沒有新的交易';
  };

  async function sync() {
    try {
      const r = await syncAll();
      toast(r === null ? '還沒有設定任何來源，請照下面的方法設定' : describe(r));
      return true;
    } catch (err) {
      toast(`同步失敗：${err.message}`);
      return false;
    } finally {
      await paint();
    }
  }

  async function copyText(text, selectEl) {
    try {
      await navigator.clipboard.writeText(text);
      toast('已複製');
    } catch {
      // 不能寫入剪貼簿時，選取文字讓使用者自己複製
      if (selectEl.select) {
        selectEl.select();
      } else {
        const range = document.createRange();
        range.selectNodeContents(selectEl);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
      }
      toast('請長按選取的文字複製');
    }
  }

  el.querySelector('[data-gmail-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const inbox = await saveGmailUrl(el.querySelector('#gmail-url').value);
      if (!inbox.gmailUrl) {
        toast('已移除 Gmail 來源');
        await paint();
        return;
      }
    } catch (err) {
      toast(err.message);
      return;
    }
    if (await sync()) toast('連接成功！之後打開記帳本就會自動記帳');
  });

  el.querySelector('[data-gist-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const id = await saveGistId(el.querySelector('#gist-url').value);
      toast(id ? '已儲存收件匣' : '已移除收件匣');
      await paint();
    } catch (err) {
      toast(err.message);
    }
  });

  el.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-act="sync"],[data-act="gen"],[data-act="test"],[data-copy],[data-fill],[data-drop],[data-forget]');
    if (!t) return;
    const act = t.dataset.act;
    if (act === 'sync') {
      t.disabled = true;
      await sync();
      t.disabled = false;
    } else if (act === 'gen') {
      const code = await generateGmailScript(el.querySelector('#gmail-senders').value);
      const area = el.querySelector('#gmail-code');
      area.value = code;
      area.hidden = false;
      await copyText(code, area);
    } else if (act === 'test') {
      const out = el.querySelector('[data-test-result]');
      const text = el.querySelector('#notice-test').value;
      const { learned, cats } = await paint();
      const item = parseInboxItem(text, 'test', todayStr());
      if (!item) {
        out.textContent = '這則不會記帳：看起來不是消費通知（或是退款、驗證碼、帳單通知）。';
      } else {
        const cat = catMap(cats).get(guessCategory(item.merchant, learned, cats));
        out.textContent = item.amount
          ? `會記成：${item.date ?? '今天'}・${cat?.icon ?? ''} ${cat?.name ?? '其他'}・${item.merchant}・${formatAmount(item.amount)}`
          : `讀不到台幣金額，會放到「待補金額」：${item.merchant}（${item.date ?? '今天'}）`;
      }
    } else if ('copy' in t.dataset) {
      const code = t.parentElement.querySelector('[data-copy-src]');
      await copyText(code.textContent, code);
    } else if (t.dataset.fill) {
      const p = (await getPending()).find((x) => x.key === t.dataset.fill);
      if (!p) return;
      setPrefill({ type: 'expense', note: p.merchant, date: p.date, pendingKey: p.key });
      location.hash = '#add';
    } else if (t.dataset.drop) {
      if (!(await confirmDialog('略過這筆交易？略過後不會記帳。', { ok: '略過' }))) return;
      await removePending(t.dataset.drop);
      await paint();
    } else if (t.dataset.forget) {
      await forgetMerchant(t.dataset.forget);
      await paint();
    }
  });

  el.querySelector('[data-act="file"]').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      toast(describe(await importFileText(await file.text())));
    } catch (err) {
      toast(err.message);
    }
    await paint();
  });

  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#prefs'));
  await paint();
}
