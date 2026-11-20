// 用 <canvas> 畫圖表，不引入外部套件。
import { formatAmount, formatCompact } from '../domain/format.js';

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function setup(canvas, height) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  if (width < 40) return null; // 還沒排版好（例如畫面正在縮放），先不畫
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.font = `12px ${cssVar('--font')}`;
  return { ctx, width, height };
}

/** 環形圖。items: [{ value, color }] */
export function drawDonut(canvas, items, total) {
  const c = setup(canvas, 200);
  if (!c) return;
  const { ctx, width, height } = c;
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) / 2 - 4;
  const inner = r * 0.64;

  const ring = (a0, a1, color) => {
    ctx.beginPath();
    ctx.arc(cx, cy, r, a0, a1);
    ctx.arc(cx, cy, inner, a1, a0, true);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
  };

  if (!total) {
    ring(0, Math.PI * 2, cssVar('--line'));
  } else {
    let a = -Math.PI / 2;
    for (const it of items) {
      const span = (it.value / total) * Math.PI * 2;
      ring(a, a + span, it.color);
      // 類別之間留一條細縫
      if (items.length > 1) {
        ctx.beginPath();
        ctx.moveTo(cx + inner * Math.cos(a), cy + inner * Math.sin(a));
        ctx.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
        ctx.strokeStyle = cssVar('--card');
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      a += span;
    }
  }

  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = cssVar('--muted');
  ctx.fillText('總支出', cx, cy - 12);
  ctx.fillStyle = cssVar('--text');
  ctx.font = `600 18px ${cssVar('--font')}`;
  ctx.fillText(formatAmount(total), cx, cy + 10);
}

/** 收入／支出並排長條圖。data: [{ label, income, expense }] */
export function drawBars(canvas, data) {
  const c = setup(canvas, 200);
  if (!c) return;
  const { ctx, width, height } = c;
  const pad = { top: 12, right: 4, bottom: 24, left: 40 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...data.flatMap((d) => [d.income, d.expense]));
  const y = (v) => pad.top + plotH - (v / max) * plotH;

  // 格線與刻度
  ctx.strokeStyle = cssVar('--line');
  ctx.fillStyle = cssVar('--muted');
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const v = (max / 3) * i;
    const yy = Math.round(y(v)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.fillText(formatCompact(Math.round(v)), pad.left - 6, yy);
  }

  const group = plotW / data.length;
  const bw = Math.min(16, group * 0.3);
  const colors = { income: cssVar('--income'), expense: cssVar('--expense') };
  const bar = (x, v, color) => {
    if (!v) return;
    const top = y(v);
    const h = pad.top + plotH - top;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, top, bw, h, [3, 3, 0, 0]);
    else ctx.rect(x, top, bw, h);
    ctx.fillStyle = color;
    ctx.fill();
  };

  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  data.forEach((d, i) => {
    const cx = pad.left + group * i + group / 2;
    bar(cx - bw - 1, d.income, colors.income);
    bar(cx + 1, d.expense, colors.expense);
    ctx.fillStyle = cssVar('--muted');
    ctx.fillText(d.label, cx, height - 6);
  });
}
