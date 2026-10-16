export type IconName = 'import' | 'grid' | 'undo' | 'redo' | 'save' | 'export' | 'chevron' | 'rail' | 'file' | 'folder' | 'close' | 'plus' | 'move' | 'more';

const paths: Record<IconName, string> = {
  import: 'M13 3H6v18h13V9m-6-6v6h6M13 3l6 6M3 13h8m-3-3 3 3-3 3',
  grid: 'M5 2.5h14A2.5 2.5 0 0 1 21.5 5v14a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 19V5A2.5 2.5 0 0 1 5 2.5ZM12 2.5v19M2.5 12h19',
  undo: 'm8 3-5 5 5 5M3 8h11a7 7 0 0 1 0 14h-3',
  redo: 'm16 3 5 5-5 5m5-5H10a7 7 0 0 0 0 14h3',
  save: 'M4 3h14l3 3v15H3V3zm3 0v7h10V3M7 21v-7h10v7',
  export: 'M13 3H5v18h15V10M13 3v7h7M13 3l7 7',
  chevron: 'm6 9 6 6 6-6',
  rail: 'M5 2.5h14A2.5 2.5 0 0 1 21.5 5v14a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 19V5A2.5 2.5 0 0 1 5 2.5ZM10 2.5v19M5.5 7h1.5m-1.5 5h1.5',
  file: 'M13 3H5v18h15V10M13 3v7h7M13 3l7 7',
  folder: 'M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10H3V6Z',
  close: 'm6 6 12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  move: 'M12 3v18M3 12h18m-12-6 3-3 3 3m-9 3-3 3 3 3m9 3-3 3-3-3m9-9 3 3-3 3',
  more: 'M4 12h.02M12 12h.02M20 12h.02',
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={name === 'more' ? 4 : 1.65} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name]} />
  </svg>;
}
