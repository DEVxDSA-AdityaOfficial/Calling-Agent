"use client";

import { createContext, useContext } from "react";
import type { User } from "./api";

export const AuthContext = createContext<{ user: User; setUser: (u: User) => void } | null>(null);

export function useUser() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useUser must be used inside the app shell");
  return ctx;
}
