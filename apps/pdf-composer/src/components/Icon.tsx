export type IconName = 'import' | 'grid' | 'undo' | 'redo' | 'save' | 'export' | 'chevron' | 'rail' | 'file' | 'close' | 'plus' | 'move';

const paths: Record<IconName, string> = {
  import: 'M13 3H6v18h13V9m-6-6v6h6M13 3l6 6M3 13h8m-3-3 3 3-3 3',
  grid: 'M3 3h18v18H3zM9 3v18M15 3v18M3 12h18',
  undo: 'M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12h-3',
  redo: 'm16 4 5 5-5 5m5-5H10a6 6 0 0 0 0 12h3',
  save: 'M4 3h14l3 3v15H3V3zm3 0v7h10V3M7 21v-7h10v7',
  export: 'M13 3H5v18h15V10M13 3v7h7M13 3l7 7',
  chevron: 'm6 9 6 6 6-6',
  rail: 'M3 3h18v18H3zM9 3v18',
  file: 'M13 3H5v18h15V10M13 3v7h7M13 3l7 7',
  close: 'm6 6 12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  move: 'M12 3v18M3 12h18m-12-6 3-3 3 3m-9 3-3 3 3 3m9 3-3 3-3-3m9-9 3 3-3 3',
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name]} />
  </svg>;
}
