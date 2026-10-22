// Small inline icon set (stroke icons, 24px grid).
type P = React.SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: P & { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden {...props}>
      {children}
    </svg>
  );
}

export const IconHome = (p: P) => (
  <Icon {...p}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" /></Icon>
);
export const IconBot = (p: P) => (
  <Icon {...p}><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 4v4M9 13h.01M15 13h.01M9 17h6" /></Icon>
);
export const IconPhone = (p: P) => (
  <Icon {...p}><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.18 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.1 9.9a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" /></Icon>
);
export const IconPhoneOff = (p: P) => (
  <Icon {...p}><path d="M10.7 13.3a16 16 0 0 0 3.4 2.6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.4 19.4 0 0 1-3.33-2.67m-2.67-3.34A19.8 19.8 0 0 1 2.1 4.18 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.1 9.9" /><path d="M22 2 2 22" /></Icon>
);
export const IconSettings = (p: P) => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></Icon>
);
export const IconPlus = (p: P) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>;
export const IconArrowRight = (p: P) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>;
export const IconArrowLeft = (p: P) => <Icon {...p}><path d="M19 12H5M11 6l-6 6 6 6" /></Icon>;
export const IconCheck = (p: P) => <Icon {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Icon>;
export const IconCheckCircle = (p: P) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="m8.5 12.5 2.5 2.5 4.5-5" /></Icon>;
export const IconUser = (p: P) => <Icon {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></Icon>;
export const IconClock = (p: P) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
export const IconMail = (p: P) => <Icon {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></Icon>;
export const IconLock = (p: P) => <Icon {...p}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></Icon>;
export const IconSparkles = (p: P) => (
  <Icon {...p}><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></Icon>
);
export const IconFlask = (p: P) => <Icon {...p}><path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" /><path d="M7 15h10" /></Icon>;
export const IconShield = (p: P) => <Icon {...p}><path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z" /><path d="m9 12 2 2 4-4" /></Icon>;
export const IconLogout = (p: P) => <Icon {...p}><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H3" /></Icon>;
export const IconChevronRight = (p: P) => <Icon {...p}><path d="m9 6 6 6-6 6" /></Icon>;
export const IconBrain = (p: P) => (
  <Icon {...p}><path d="M9.5 3A2.5 2.5 0 0 0 7 5.5v.3A3 3 0 0 0 4.5 9a3 3 0 0 0 .7 1.9A3 3 0 0 0 4 13.5 3 3 0 0 0 7 16.5v.5A3 3 0 0 0 10 20h0a2 2 0 0 0 2-2V5a2 2 0 0 0-2.5-2z" /><path d="M14.5 3A2.5 2.5 0 0 1 17 5.5v.3A3 3 0 0 1 19.5 9a3 3 0 0 1-.7 1.9 3 3 0 0 1 1.2 2.6 3 3 0 0 1-3 3v.5a3 3 0 0 1-3 3h0a2 2 0 0 1-2-2" /></Icon>
);

/** Brand mark: audio waveform bars. */
export function Waveform({ className = "" }: { className?: string }) {
  const bars = [6, 12, 18, 10, 16, 8];
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      {bars.map((h, i) => (
        <rect key={i} x={2 + i * 3.6} y={12 - h / 2} width="2" height={h} rx="1" fill="currentColor" />
      ))}
    </svg>
  );
}
