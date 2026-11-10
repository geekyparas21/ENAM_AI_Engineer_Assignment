import type { SVGProps } from "react";

function Base({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

type P = SVGProps<SVGSVGElement>;

export const BriefIcon = (p: P) => (<Base {...p}><path d="M5 6h14M5 12h14M5 18h8" /></Base>);
export const BellIcon = (p: P) => (
  <Base {...p}><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Z" /><path d="M10 20a2 2 0 0 0 4 0" /></Base>
);
export const SearchIcon = (p: P) => (<Base {...p}><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5" /></Base>);
export const SlidersIcon = (p: P) => (
  <Base {...p}><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></Base>
);
export const StarIcon = ({ filled, ...p }: P & { filled?: boolean }) => (
  <Base {...p} fill={filled ? "currentColor" : "none"}>
    <path d="m12 4 2.5 5.1 5.6.8-4 4 .9 5.6-5-2.7-5 2.7.9-5.6-4-4 5.6-.8L12 4Z" />
  </Base>
);
export const CheckIcon = (p: P) => (<Base {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Base>);
export const MuteIcon = (p: P) => (
  <Base {...p}><path d="M6 16V11a6 6 0 0 1 9.5-4.9M18 11v5l1.5 2H9" /><path d="m4 4 16 16" /></Base>
);
export const ChevronIcon = (p: P) => (<Base {...p}><path d="m7 10 5 5 5-5" /></Base>);
export const LinkIcon = (p: P) => (<Base {...p}><path d="M9 6h9v9M18 6 7 17" /></Base>);
export const WarnIcon = (p: P) => (
  <Base {...p}><path d="M12 4 2.8 19h18.4L12 4Z" /><path d="M12 10v4M12 16.8v.2" /></Base>
);
export const InfoIcon = (p: P) => (<Base {...p}><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 7.8v.2" /></Base>);
