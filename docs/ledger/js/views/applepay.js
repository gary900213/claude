// Apple Pay 自動記帳：設定 Gist 收件匣、同步、從檔案匯入、補記缺金額的交易、設定教學。
import {
  forgetMerchant, getInbox, getLearned, getPending, importFileText, removePending, saveGistId, syncGist,
} from '../services/inbox.js';
import { listCategories } from '../services/categories.js';
import { goBack } from '../router.js';
import { setPrefill } from './edit.js';
import { catMap, confirmDialog, esc, subHeader, toast } from './components.js';

const TEMPLATE = '{"amount":"〔金額〕","merchant":"〔商家〕","time":"〔目前日期〕"}';

export async function render(el) {
  el.innerHTML = `
    ${subHeader('Apple Pay 自動記帳')}
    <section class="card">
      <div class="section-head"><h2>收件匣（GitHub Gist）</h2></div>
      <form class="gist-form" data-gist-form novalidate>
        <label class="field">
          <span>Gist 網址</span>
          <input id="gist-url" name="gist" inputmode="url" autocomplete="off" placeholder="https://gist.github.com/…">
        </label>
        <div class="btn-row">
          <button class="btn" type="submit">儲存</button>
          <button class="btn primary" type="button" data-act="sync">立即同步</button>
        </div>
      </form>
      <p class="hint" data-status></p>
    </section>

    <section class="card" data-pending-card hidden>
      <div class="section-head"><h2>待補金額</h2></div>
      <p class="hint">這些交易捷徑沒有帶到金額，點「補記」填上金額就好。</p>
      <ul class="tx-list" data-pending></ul>
    </section>

    <section class="card">
      <div class="section-head"><h2>從檔案匯入</h2></div>
      <p class="hint">如果捷徑是把交易「附加到 iCloud 雲碟的文字檔」，在這裡選那個檔案。已經匯入過的不會重複記。</p>
      <div class="btn-row">
        <label class="btn">選擇檔案<input type="file" accept=".txt,.json,text/plain,application/json" data-act="file" hidden></label>
      </div>
    </section>

    <section class="card" data-learned-card hidden>
      <div class="section-head"><h2>記住的商店分類</h2></div>
      <p class="hint">改過 Apple Pay 紀錄的類別後，同一家店（含其他分店）之後會自動用這個類別。</p>
      <ul class="cat-rows" data-learned></ul>
    </section>

    <section class="card guide">
      <div class="section-head"><h2>設定教學（只要做一次）</h2></div>
      <h3>1. 建立收件匣</h3>
      <ol>
        <li>電腦打開 <span class="mono">gist.github.com</span>，登入 GitHub。</li>
        <li>檔名填 <span class="mono">ledger.txt</span>，內容隨便打一個字，按「Create <b>secret</b> gist」。</li>
        <li>把網址列的網址貼到上面的「Gist 網址」，按儲存。</li>
      </ol>
      <h3>2. 建立 GitHub 權杖（讓捷徑可以寫入）</h3>
      <ol>
        <li>打開 GitHub 的 Settings → Developer settings → Personal access tokens → <b>Fine-grained tokens</b> → Generate new token。</li>
        <li>Expiration 選久一點（例如 1 年），Account permissions 裡只把 <b>Gists</b> 設成 <b>Read and write</b>，其他都不用開。</li>
        <li>產生後複製那串 <span class="mono">github_pat_…</span>，等一下貼到捷徑裡。</li>
      </ol>
      <h3>3. iPhone 捷徑自動化</h3>
      <ol>
        <li>打開「捷徑」App → 下方「自動化」→ 右上「＋」→ 選「<b>交易</b>」。</li>
        <li>勾選要記帳的卡片，選「<b>立即執行</b>」，按下一步 →「新增空白捷徑」。</li>
        <li>加入動作「<b>文字</b>」，內容貼上：
          <div class="copy-box"><code data-copy-src>${esc(TEMPLATE)}</code><button class="btn small" type="button" data-copy>複製</button></div>
          再把〔金額〕、〔商家〕換成「捷徑輸入」的<b>金額</b>、<b>商家</b>變數，〔目前日期〕換成「目前日期」變數（點它把日期格式改成「自訂」：<span class="mono">yyyy-MM-dd HH:mm</span>）。
        </li>
        <li>加入動作「<b>取得 URL 內容</b>」，網址填：
          <div class="copy-box"><code data-copy-src data-api-url>https://api.github.com/gists/〔Gist ID〕/comments</code><button class="btn small" type="button" data-copy>複製</button></div>
          展開後：方法選 <b>POST</b>；標頭新增 <span class="mono">Authorization</span> 值 <span class="mono">Bearer 〔你的權杖〕</span>；要求本文選 <b>JSON</b>，新增欄位 <span class="mono">body</span>（文字）值選上一步的「文字」。
        </li>
        <li>完成。之後用 Apple Pay 感應付款，打開記帳本就會自動記上。</li>
      </ol>
      <h3>不想用 GitHub？</h3>
      <p>第 3 步的「取得 URL 內容」改成「<b>附加到文字檔</b>」，存到 iCloud 雲碟（例如 <span class="mono">記帳收件匣.txt</span>），要記帳時用上面的「從檔案匯入」選這個檔案。</p>
      <h3>隱私</h3>
      <p>Secret gist 不會出現在搜尋或你的個人頁面，但<b>知道網址的人看得到</b>內容（金額、商店、時間）。不要把 Gist 網址分享出去。權杖只放在你手機的捷徑裡，記帳本不會存。</p>
      <h3>限制</h3>
      <p>只有在實體商店<b>感應付款</b>會觸發，網購的 Apple Pay 不會。有些卡片可能不會帶入金額，會放在「待補金額」。</p>
    </section>`;

  const form = el.querySelector('[data-gist-form]');
  const statusEl = el.querySelector('[data-status]');

  async function paint() {
    const [inbox, pending, learned, cats] = await Promise.all([
      getInbox(), getPending(), getLearned(), listCategories({ includeHidden: true }),
    ]);
    const map = catMap(cats);
    if (document.activeElement !== form.elements.gist) {
      form.elements.gist.value = inbox.gistId ? `https://gist.github.com/${inbox.gistId}` : '';
    }
    el.querySelector('[data-api-url]').textContent =
      `https://api.github.com/gists/${inbox.gistId || '〔Gist ID〕'}/comments`;
    statusEl.textContent = !inbox.gistId
      ? '還沒設定收件匣，請先照下面的教學建立。'
      : inbox.lastError
        ? `上次同步失敗：${inbox.lastError}`
        : inbox.lastSyncAt
          ? `上次同步：${new Date(inbox.lastSyncAt).toLocaleString('zh-TW')}。打開記帳本時會自動同步。`
          : '已設定，按「立即同步」試試看。';
    statusEl.classList.toggle('error', Boolean(inbox.lastError));

    el.querySelector('[data-pending-card]').hidden = !pending.length;
    el.querySelector('[data-pending]').innerHTML = pending
      .map(
        (p) => `
        <li class="pending-row">
          <span class="tx-main"><span class="tx-cat">${esc(p.merchant || 'Apple Pay')}</span>
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
    return pending;
  }

  const report = (r) => {
    if (!r) return;
    const parts = [];
    if (r.added) parts.push(`記入 ${r.added} 筆`);
    if (r.pending) parts.push(`${r.pending} 筆待補金額`);
    toast(parts.length ? `已同步：${parts.join('，')}` : '沒有新的交易');
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const id = await saveGistId(form.elements.gist.value);
      toast(id ? '已儲存收件匣' : '已移除收件匣');
      form.elements.gist.blur();
      await paint();
    } catch (err) {
      toast(err.message);
    }
  });

  el.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-act="sync"],[data-copy],[data-fill],[data-drop],[data-forget]');
    if (!t) return;
    if (t.dataset.act === 'sync') {
      t.disabled = true;
      try {
        const r = await syncGist();
        if (r === null) toast('請先填入 Gist 網址並儲存');
        report(r);
      } catch (err) {
        toast(err.message);
      } finally {
        t.disabled = false;
        await paint();
      }
    } else if ('copy' in t.dataset) {
      const code = t.parentElement.querySelector('[data-copy-src]');
      try {
        await navigator.clipboard.writeText(code.textContent);
        toast('已複製');
      } catch {
        // 不能寫入剪貼簿時，選取文字讓使用者自己複製
        const range = document.createRange();
        range.selectNodeContents(code);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        toast('請長按選取的文字複製');
      }
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
      report(await importFileText(await file.text()));
    } catch (err) {
      toast(err.message);
    }
    await paint();
  });

  el.querySelector('[data-act="back"]').addEventListener('click', () => goBack('#prefs'));
  await paint();
}

