"use client";

import { Suspense } from "react";
import OrderPage from "./order-client";
import styles from "./page.module.css";

export default function OrderPageSuspense() {
  return (
    <Suspense
      fallback={
        <div className={styles.container}>
          <main className={styles.main}>
            <div className={styles.loading}>Loading…</div>
          </main>
        </div>
      }
    >
      <OrderPage />
    </Suspense>
  );
}
