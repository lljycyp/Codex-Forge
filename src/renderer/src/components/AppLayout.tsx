import type { ReactNode } from "react";
import { Layout, Typography } from "antd";
import { Minus, Square, X } from "lucide-react";
import type { ViewKey, ViewMeta } from "../types";

const { Header, Sider } = Layout;

type MenuItem = {
  key: ViewKey;
  label: string;
  icon: ReactNode;
};

type AppLayoutProps = {
  activeView: ViewKey;
  currentView: ViewMeta;
  menuItems: MenuItem[];
  taskText: string;
  topbarAction: ReactNode;
  children: ReactNode;
  onChangeView: (view: ViewKey) => void;
};

export function AppLayout({
  activeView,
  currentView,
  menuItems,
  taskText,
  topbarAction,
  children,
  onChangeView,
}: AppLayoutProps) {
  return (
    <Layout className="app-shell">
      <div className="titlebar">
        <div className="titlebar-brand">
          <div className="titlebar-logo">C</div>
          <div className="titlebar-copy">
            <span className="titlebar-name">Codex 多账号启动器</span>
            <span className="titlebar-desc">账号隔离、启动与诊断工作台</span>
          </div>
        </div>
        <div className="titlebar-drag" />
        <div className="window-controls">
          <button
            className="window-control"
            title="最小化"
            onClick={() => window.launcherApi.minimizeWindow()}
          >
            <Minus />
          </button>
          <button
            className="window-control"
            title="最大化"
            onClick={() => window.launcherApi.toggleMaximizeWindow()}
          >
            <Square />
          </button>
          <button
            className="window-control close"
            title="关闭"
            onClick={() => window.launcherApi.closeWindow()}
          >
            <X />
          </button>
        </div>
      </div>
      <Layout className="app-body">
        <Sider width={236} className="side">
          <nav className="nav">
            <div className="nav-section">
              <div className="nav-section-title">工作区</div>
              {menuItems.slice(0, 2).map((item) => (
                <NavButton
                  key={item.key}
                  item={item}
                  active={activeView === item.key}
                  onChangeView={onChangeView}
                />
              ))}
            </div>
            <div className="nav-section">
              <div className="nav-section-title">维护</div>
              {menuItems.slice(2).map((item) => (
                <NavButton
                  key={item.key}
                  item={item}
                  active={activeView === item.key}
                  onChangeView={onChangeView}
                />
              ))}
            </div>
          </nav>
        </Sider>
        <Layout className="main-layout">
          <Header className="topbar">
            <PageHeading currentView={currentView} />
            {topbarAction}
          </Header>
          {children}
        </Layout>
      </Layout>
    </Layout>
  );
}

function NavButton({
  item,
  active,
  onChangeView,
}: {
  item: MenuItem;
  active: boolean;
  onChangeView: (view: ViewKey) => void;
}) {
  return (
    <button
      className={active ? "nav-item active" : "nav-item"}
      onClick={() => onChangeView(item.key)}
    >
      {item.icon}
      <span>{item.label}</span>
    </button>
  );
}

function PageHeading({ currentView }: { currentView: ViewMeta }) {
  return (
    <div className="page-heading">
      <Typography.Title level={2}>{currentView.title}</Typography.Title>
      <Typography.Text type="secondary">
        {currentView.description}
      </Typography.Text>
    </div>
  );
}
