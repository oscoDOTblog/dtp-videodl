"use client";

import AppHeader from "./AppHeader";

export default function AppShell({ children, onLogout }) {
  return (
    <>
      <AppHeader onLogout={onLogout} />
      {children}
    </>
  );
}
