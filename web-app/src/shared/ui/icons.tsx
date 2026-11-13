const paths = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l1.5-4.1A8.5 8.5 0 1 1 21 11.5ZM8 11h8m-8 4h5",
  plan: "M9 5H5v16h14V5h-4M9 3h6v4H9zM8 12l1 1 2-2m2 2h3m-8 4 1 1 2-2m2 2h3",
  actions: "M7 3h7l4 4v14H6V4a1 1 0 0 1 1-1Zm7 0v5h5M9 12h6m-6 4h6",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Zm-8 12a2 2 0 0 0 4 0",
  arrow: "M4 12h15m-6-6 6 6-6 6",
  logout: "M10 4H5v16h5m4-12 4 4-4 4m-5-4h10",
  spark: "M12 2c1 7 3 9 10 10-7 1-9 3-10 10-1-7-3-9-10-10 7-1 9-3 10-10Z",
} as const;

export function Icon({ name }: { name: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
