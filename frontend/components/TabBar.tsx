"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { applyTheme, usePrefs } from "@/lib/store";
import { BellIcon, BriefIcon, SearchIcon, SlidersIcon } from "./icons";

const TABS = [
  { href: "/", label: "Brief", Icon: BriefIcon },
  { href: "/alerts", label: "Alerts", Icon: BellIcon },
  { href: "/research", label: "Research", Icon: SearchIcon },
  { href: "/settings", label: "Settings", Icon: SlidersIcon },
];

export function TabBar() {
  const path = usePathname();
  const { theme } = usePrefs();
  useEffect(() => applyTheme(theme), [theme]);

  return (
    <nav aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur pb-[env(safe-area-inset-bottom)]">
      <ul className="mx-auto flex max-w-xl">
        {TABS.map(({ href, label, Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <li key={href} className="flex-1">
              <Link href={href} aria-current={active ? "page" : undefined}
                className={`flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${
                  active ? "text-accent" : "text-muted"}`}>
                <Icon />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
