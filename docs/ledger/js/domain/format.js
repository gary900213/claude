// 日期、月份、金額的格式化與計算。全部是純函式。
// 日期一律用本地日期字串 "YYYY-MM-DD"、月份用 "YYYY-MM"。

export const pad2 = (n) => String(n).padStart(2, '0');

export function toDateStr(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export const todayStr = () => toDateStr(new Date());

export const monthOf = (date) => date.slice(0, 7);

export const isMonthStr = (s) => typeof s === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(s);

export function addMonths(month, n) {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

/** 回傳該月第一天與最後一天，例如 ["2026-02-01", "2026-02-28"] */
export function monthRange(month) {
  const [y, m] = month.split('-').map(Number);
  const last = new Date(y, m, 0).getDate();
  return [`${month}-01`, `${month}-${pad2(last)}`];
}

export function formatMonth(month) {
  const [y, m] = month.split('-');
  return `${y} 年 ${Number(m)} 月`;
}

const WEEKDAYS = '日一二三四五六';

/** "2026-11-09" → "11/9（週一）" */
export function formatDay(date) {
  const [y, m, d] = date.split('-').map(Number);
  const w = new Date(y, m - 1, d).getDay();
  return `${m}/${d}（週${WEEKDAYS[w]}）`;
}

const withCommas = (n) => String(Math.abs(Math.trunc(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** 1234 → "$1,234"（不帶正負號） */
export const formatAmount = (n) => `$${withCommas(n)}`;

/** -1234 → "-$1,234" */
export const formatSigned = (n) => `${n < 0 ? '-' : ''}${formatAmount(n)}`;

/** 圖表座標軸用的短格式：12000 → "1.2萬" */
export function formatCompact(n) {
  if (Math.abs(n) >= 10000) {
    const v = n / 10000;
    return `${Math.abs(v) >= 10 ? Math.round(v) : Math.round(v * 10) / 10}萬`;
  }
  return withCommas(n);
}
