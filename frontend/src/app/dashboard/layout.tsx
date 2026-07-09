"use client";
import { useEffect } from "react";
import { useUser, useAuth } from "@clerk/nextjs";
import Sidebar from "@/components/ui/Sidebar";
import { api, setAuthTokenGetter } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoaded } = useUser();
  const { getToken } = useAuth();

  // Register the Clerk token getter during render — before children mount —
  // so data fetches fired from child components' effects already carry the
  // Authorization header. getToken is stable across renders.
  setAuthTokenGetter(getToken);

  useEffect(() => {
    if (!isLoaded || !user) return;
    // Ensure a matching User row exists in the backend DB (idempotent upsert).
    // The backend verifies clerk_id against the session token's subject.
    api.auth
      .sync(user.id, user.primaryEmailAddress?.emailAddress ?? "")
      .catch(() => {
        /* non-critical — subsequent API calls return 401 if auth is broken */
      });
  }, [isLoaded, user]);

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">{children}</main>
    </div>
  );
}
