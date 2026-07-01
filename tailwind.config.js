/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/renderer/index.html", "./src/renderer/src/**/*.{ts,tsx}"],
  corePlugins: {
    preflight: false
  },
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eefcf8",
          100: "#d6f5ed",
          600: "#0d9488",
          700: "#0d9488"
        },
        shell: {
          surface: "#f7f9fc",
          line: "#d8e1ec",
          muted: "#667085"
        }
      },
      backgroundImage: {
        "shell-gradient":
          "linear-gradient(120deg, rgba(15, 118, 110, 0.92) 0%, rgba(20, 184, 166, 0.46) 28%, rgba(226, 245, 242, 0.78) 58%, rgba(232, 240, 255, 0.96) 100%)",
        "brand-gradient": "linear-gradient(135deg, #0f766e, #1d4ed8)",
        "detail-gradient": "linear-gradient(135deg, rgba(15, 118, 110, 0.1), rgba(37, 99, 235, 0.07))"
      },
      borderRadius: {
        card: "8px",
        panel: "10px"
      },
      boxShadow: {
        panel: "0 22px 55px rgba(15, 23, 42, 0.16), 0 1px 0 rgba(255, 255, 255, 0.8) inset"
      },
      fontFamily: {
        sans: ["Microsoft YaHei UI", "Segoe UI", "sans-serif"],
        mono: ["Cascadia Code", "Consolas", "Courier New", "monospace"]
      }
    }
  },
  plugins: []
};
