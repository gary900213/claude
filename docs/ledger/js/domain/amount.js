// 記帳鍵盤的金額算式：只有正整數和加減，例如 "120+35-10"。純函式。

export const MAX_DIGITS = 9;
export const MAX_LENGTH = 30;

const isOp = (c) => c === '+' || c === '-';

/** 算式算出來的金額；格式不對回傳 NaN。結尾多一個運算子會被忽略。 */
export function evalAmount(expr) {
  const s = String(expr ?? '').replace(/[,\s]/g, '').replace(/[+-]$/, '');
  if (!/^\d+([+-]\d+)*$/.test(s)) return NaN;
  return s.match(/[+-]?\d+/g).reduce((sum, n) => sum + Number(n), 0);
}

export const hasOperator = (expr) => /\d[+-]\d/.test(expr);

/** 按一個鍵之後的新算式。key：'0'~'9'、'00'、'+'、'-'、'back'、'clear' */
export function pressKey(expr, key) {
  if (key === 'clear') return '';
  if (key === 'back') return expr.slice(0, -1);

  if (isOp(key)) {
    if (!expr) return expr; // 不能用運算子開頭
    if (isOp(expr.at(-1))) return expr.slice(0, -1) + key; // 連按運算子：換掉前一個
    return expr.length < MAX_LENGTH ? expr + key : expr;
  }

  if (!/^(\d|00)$/.test(key)) return expr;
  const current = expr.match(/\d*$/)[0]; // 正在輸入的那個數字
  if (current === '0') {
    // 開頭的 0 直接換成新數字，不會出現 "05"
    return key === '00' || key === '0' ? expr : expr.slice(0, -1) + key;
  }
  if (current === '' && key === '00') return expr + '0';
  if (current.length + key.length > MAX_DIGITS || expr.length + key.length > MAX_LENGTH) return expr;
  return expr + key;
}
