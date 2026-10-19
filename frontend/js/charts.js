// Chart.js helpers with one palette: conventional ATC in warm grey/orange, SkyControl in teal.
import { onCleanup } from './core.js';

export const C = {
  base: '#c98a5a', baseSoft: '#e9cdb7', sky: '#087f83', skySoft: '#9fd8d2', ink: '#13303a', grid: '#e6eef0',
  red: '#c0444a', amber: '#e2a03a', violet: '#6d5bd0', blue: '#2f6fb3', green: '#2f8f6b', grey: '#9fb0b5',
  series: ['#087f83', '#c98a5a', '#6d5bd0', '#2f6fb3', '#e2a03a', '#c0444a', '#2f8f6b', '#7a8b91', '#d06d9b', '#4bb3c9'],
};

const base = (extra = {}) => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { labels: { boxWidth: 12, boxHeight: 12, font: { size: 11 } } },
    tooltip: { mode: 'index', intersect: false },
    ...extra.plugins,
  },
  scales: extra.scales,
  ...extra.options,
});

function make(canvas, config) {
  if (!canvas || !window.Chart) return null;
  const chart = new window.Chart(canvas.getContext('2d'), config);
  onCleanup(() => chart.destroy());
  return chart;
}

const axis = (title, extra = {}) => ({ title: { display: !!title, text: title, font: { size: 11 } }, grid: { color: C.grid }, ticks: { font: { size: 10 } }, ...extra });

export function bars(canvas, labels, datasets, { y = '', x = '', horizontal = false, stacked = false, legend = true } = {}) {
  return make(canvas, {
    type: 'bar',
    data: { labels, datasets: datasets.map((d, i) => ({ borderRadius: 4, maxBarThickness: 46, backgroundColor: d.color || C.series[i % C.series.length], ...d })) },
    options: base({
      plugins: { legend: { display: legend } },
      options: { indexAxis: horizontal ? 'y' : 'x' },
      scales: { x: axis(horizontal ? y : x, { stacked }), y: axis(horizontal ? x : y, { stacked, beginAtZero: true }) },
    }),
  });
}

export function lines(canvas, labels, datasets, { y = '', y1 = '', x = '', stacked = false, fill = false } = {}) {
  return make(canvas, {
    type: 'line',
    data: { labels, datasets: datasets.map((d, i) => ({ borderColor: d.color || C.series[i % C.series.length], backgroundColor: (d.color || C.series[i % C.series.length]) + '33',
      pointRadius: 0, borderWidth: 2, tension: 0.25, fill, ...d })) },
    options: base({ scales: {
      x: axis(x, { ticks: { maxTicksLimit: 10, font: { size: 10 } } }),
      y: axis(y, { stacked, beginAtZero: true }),
      ...(datasets.some((d) => d.yAxisID === 'y1') ? { y1: axis(y1, { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false } }) } : {}),
    } }),
  });
}

export function scatter(canvas, datasets, { x = '', y = '' } = {}) {
  return make(canvas, {
    type: 'scatter',
    data: { datasets: datasets.map((d, i) => ({ backgroundColor: (d.color || C.series[i]) + 'aa', pointRadius: 3, ...d })) },
    options: base({ plugins: { tooltip: { mode: 'nearest' } }, scales: { x: axis(x), y: axis(y, { beginAtZero: true }) } }),
  });
}

export function doughnut(canvas, labels, values, colors) {
  return make(canvas, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors || C.series, borderWidth: 2 }] },
    options: base({ options: { cutout: '62%' }, plugins: { legend: { position: 'right' } } }),
  });
}
