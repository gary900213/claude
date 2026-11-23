// 首頁：本月收支摘要＋最近紀錄。
import { countTransactions, listByMonth, listRecent } from '../services/ledger.js';
import { backupDue, exportJSON, snoozeBackup } from '../services/backup.js';
import { bindInstall, installCard } from './install.js';
import { PREVIEW } from '../config.js';
import { listCategories } from '../services/categories.js';
import { getBudgets } from '../services/budget.js';
import { budgetStatus } from '../domain/budget.js';
import { formatAmount, formatMonth, monthOf, todayStr } from '../domain/format.js';
import { groupByDate, spentOn, summarize } from '../domain/stats.js';
import { budgetCard, catMap, emptyState, groupedList, summaryCards, toast } from './components.js';

export async function render(el) {
  const today = todayStr();
  const month = monthOf(today);
  const [monthTxs, recent, cats, budgets, count] = await Promise.all([
    listByMonth(month),
    listRecent(20),
    listCategories({ includeHidden: true }),
    getBudgets(),
    countTransactions(),
  ]);
  const backup = await backupDue(count);

  el.innerHTML = `
    <header class="page-head home-head">
      <h1>${formatMonth(month)}</h1>
      ${(() => {
        const spent = spentOn(monthTxs, today);
        return spent
          ? `<span class="today-spent">今天花了 <b class="expense">${formatAmount(spent)}</b></span>`
          : '<span class="today-spent muted">今天還沒有支出</span>';
      })()}
    </header>
    ${installCard()}
    ${summaryCards(summarize(monthTxs))}
    ${
      backup
        ? `<section class="card notice-card" data-backup>
            <p>💾 ${backup.days === null ? '你還沒有備份過' : `上次備份是 ${backup.days} 天前`}。資料只存在這支手機，換手機或清除瀏覽器資料就會不見。</p>
            <div class="btn-row">
              <button class="btn primary" type="button" data-backup-act="now">立即備份</button>
              <button class="btn" type="button" data-backup-act="later">稍後</button>
            </div>
          </section>`
        : ''
    }
    ${
      budgets.length
        ? budgetCard(budgetStatus(monthTxs, budgets, cats, month, today))
        : recent.length
          ? '<a class="card link-card" href="#budget"><span>🎯 設定每月預算，隨時知道還能花多少</span><span aria-hidden="true">›</span></a>'
          : ''
    }
    <section class="card">
      <div class="section-head">
        <h2>最近紀錄</h2>
        ${recent.length ? '<a href="#list">看全部 ›</a>' : ''}
      </div>
      ${recent.length ? groupedList(groupByDate(recent), catMap(cats)) : PREVIEW ? emptyState('還沒有任何紀錄，按右下角的「＋」記第一筆吧') : FIRST_STEPS}
    </section>`;

  bindInstall(el);
  el.querySelector('[data-backup]')?.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-backup-act]')?.dataset.backupAct;
    if (!act) return;
    try {
      if (act === 'now') {
        await exportJSON();
        toast('已匯出備份，記得存到雲端硬碟或傳給自己');
      } else {
        await snoozeBackup();
      }
      el.querySelector('[data-backup]').remove();
    } catch (err) {
      toast(err.message);
    }
  });
}

const FIRST_STEPS = `
  <div class="first-steps">
    <p><b>歡迎使用記帳本！</b>三個步驟開始：</p>
    <ol>
      <li>按右下角的「<b>＋</b>」記第一筆，金額可以直接算加減，例如 120+35。</li>
      <li>到「設定 → <a href="#budget">每月預算</a>」設定預算，首頁會告訴你每天還能花多少。</li>
      <li>想要刷卡後自動記帳，到「設定 → <a href="#applepay">刷卡自動記帳</a>」照著設定一次。</li>
    </ol>
    <p class="muted">資料只存在這支手機，別人看不到。記得偶爾到「設定」匯出備份。</p>
  </div>`;
