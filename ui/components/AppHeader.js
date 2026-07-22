"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import styles from "./AppHeader.module.css";

export default function AppHeader() {
  const pathname = usePathname();
  const [activeCount, setActiveCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetch("/api/queue/jobs");
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled) setActiveCount(Number(data.activeCount) || 0);
      } catch {
        // ignore badge errors
      }
    };

    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [pathname]);

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          VideoDL
        </Link>
        <nav className={styles.nav}>
          <Link href="/" className={pathname === "/" ? styles.active : undefined}>
            Home
          </Link>
          <Link
            href="/queue"
            className={pathname === "/queue" ? styles.active : undefined}
          >
            Current Queue
            {activeCount > 0 && <span className={styles.badge}>{activeCount}</span>}
          </Link>
        </nav>
      </div>
    </header>
  );
}
