import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#166534",
          borderRadius: 8,
          fontFamily: "Microsoft YaHei UI, Segoe UI, sans-serif"
        },
        components: {
          Button: {
            controlHeight: 36,
            paddingContentHorizontal: 14
          }
        }
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
