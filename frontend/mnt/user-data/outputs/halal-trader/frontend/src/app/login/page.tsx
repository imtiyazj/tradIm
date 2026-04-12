"use client";
import { SignIn } from "@clerk/nextjs";

export default function LoginPage() {
  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: "32px",
    }}>
      {/* Logo */}
      <div style={{ textAlign: "center" }}>
        <div style={{
          fontFamily: "var(--mono)",
          fontSize: "11px",
          color: "var(--green)",
          letterSpacing: "0.2em",
          textTransform: "uppercase",
          marginBottom: "8px",
        }}>
          ◆ Halal Trader
        </div>
        <div style={{
          fontFamily: "var(--serif)",
          fontSize: "32px",
          fontWeight: 300,
          fontStyle: "italic",
          color: "var(--text)",
        }}>
          Private access only
        </div>
        <div style={{
          fontFamily: "var(--mono)",
          fontSize: "11px",
          color: "var(--text3)",
          marginTop: "8px",
        }}>
          AI-powered Shariah-compliant stock research
        </div>
      </div>

      {/* Clerk sign-in */}
      <SignIn
        appearance={{
          variables: {
            colorBackground:      "#111114",
            colorText:            "#e8e8f0",
            colorTextSecondary:   "#8888a0",
            colorInputBackground: "#18181d",
            colorInputText:       "#e8e8f0",
            colorPrimary:         "#00c896",
            borderRadius:         "6px",
          },
          elements: {
            card:             { boxShadow: "none", border: "1px solid #222228" },
            headerTitle:      { display: "none" },
            headerSubtitle:   { display: "none" },
            socialButtonsBlockButton: {
              background: "#18181d",
              border: "1px solid #2e2e38",
              color: "#e8e8f0",
            },
          },
        }}
      />
    </div>
  );
}
