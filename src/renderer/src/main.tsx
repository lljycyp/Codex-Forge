import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { I18nProvider, useI18n } from "./i18n";
import "./styles.css";

function Root() {
  const { language } = useI18n();
  document.documentElement.lang = language;
  return (
    <ConfigProvider
      locale={language === "en-US" ? enUS : zhCN}
      theme={{
        token: {
          colorPrimary: "#0d9488",
          borderRadius: 8,
          fontFamily: "Microsoft YaHei UI, Segoe UI, sans-serif",
        },
        components: {
          Button: {
            controlHeight: 36,
            paddingContentHorizontal: 14,
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <I18nProvider>
      <Root />
    </I18nProvider>
  </React.StrictMode>,
);
