import type { ReactNode } from "react";
import { Layout, Typography } from "antd";
import { Minus, Square, X } from "lucide-react";
import type { ViewKey, ViewMeta } from "../types";

const { Header, Sider } = Layout;

const windowButtonClass =
  "flex h-12 w-[46px] items-center justify-center border-0 bg-transparent text-[#263647] transition-colors duration-200 hover:bg-white/30 hover:text-slate-900";

const navButtonBaseClass =
  "flex h-11 w-full items-center gap-2.5 rounded-[9px] border border-transparent bg-transparent px-2.5 text-left text-sm font-bold text-white/90 hover:border-white/20 hover:bg-white/20 hover:text-white hover:[&_svg]:text-white [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:shrink-0 [&_svg]:text-white/75";

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
    <Layout className="grid h-screen grid-rows-[48px_minmax(0,1fr)] overflow-hidden bg-[#e8f4f4] bg-shell-gradient">
      <div className="grid h-12 grid-cols-[auto_minmax(0,1fr)_auto] items-center border-b-0 bg-transparent [-webkit-app-region:drag]">
        <div className="flex min-w-0 items-center gap-2.5 pl-[18px]">
          <div className="grid h-8 w-8 place-items-center rounded-card bg-brand-gradient text-[15px] font-black text-white shadow-[0_10px_24px_rgba(15,118,110,0.24)]">
            C
          </div>
          <div className="flex min-w-0 items-baseline gap-2.5 whitespace-nowrap">
            <span className="text-sm font-extrabold text-white">
              Codex 多账号切换器
            </span>
          </div>
        </div>
        <div className="h-full" />
        <div className="grid h-12 grid-cols-3 [-webkit-app-region:no-drag]">
          <button
            className={windowButtonClass}
            title="最小化"
            onClick={() => window.launcherApi.minimizeWindow()}
          >
            <Minus size={14} strokeWidth={2} />
          </button>
          <button
            className={windowButtonClass}
            title="最大化"
            onClick={() => window.launcherApi.toggleMaximizeWindow()}
          >
            <Square size={14} strokeWidth={2} />
          </button>
          <button
            className={`${windowButtonClass} hover:bg-[#ff4d4f] hover:text-white`}
            title="关闭"
            onClick={() => window.launcherApi.closeWindow()}
          >
            <X size={14} strokeWidth={2} />
          </button>
        </div>
      </div>
      <Layout className="h-full min-h-0 overflow-hidden bg-transparent">
        <Sider
          width={236}
          className="h-full !min-w-[236px] !max-w-[236px] !basis-[236px] overflow-hidden border-r-0 !bg-transparent px-3.5 pb-3.5 pt-3 max-[960px]:!min-w-[210px] max-[960px]:!max-w-[210px] max-[960px]:!basis-[210px] [&_.ant-layout-sider-children]:grid [&_.ant-layout-sider-children]:h-full [&_.ant-layout-sider-children]:min-h-0 [&_.ant-layout-sider-children]:grid-rows-[1fr_auto] [&_.ant-layout-sider-children]:gap-4"
        >
          <nav className="grid min-h-0 content-start gap-1.5 pt-1">
            {menuItems.map((item) => (
              <NavButton
                key={item.key}
                item={item}
                active={activeView === item.key}
                onChangeView={onChangeView}
              />
            ))}
          </nav>
        </Sider>
        <Layout className="relative mb-3.5 mr-3.5 h-[calc(100%-14px)] min-w-0 overflow-hidden rounded-panel bg-shell-surface shadow-panel">
          <Header className="flex h-[88px] flex-none items-center justify-between gap-4 overflow-visible border-b border-[#e4ebf3] !bg-white px-[30px] pb-4 pt-5 leading-normal [&>*]:[-webkit-app-region:no-drag]">
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
      className={
        active
          ? `${navButtonBaseClass} border-white/20 bg-white/20 text-white [&_svg]:text-white`
          : navButtonBaseClass
      }
      onClick={() => onChangeView(item.key)}
    >
      {item.icon}
      <span>{item.label}</span>
    </button>
  );
}

function PageHeading({ currentView }: { currentView: ViewMeta }) {
  return (
    <div className="flex min-w-0 flex-col justify-center gap-0.5 max-[960px]:hidden [&_h2]:!mb-1 [&_h2]:!text-2xl [&_h2]:!font-extrabold [&_h2]:!leading-tight [&_h2]:!tracking-normal">
      <Typography.Title level={2}>{currentView.title}</Typography.Title>
      <Typography.Text type="secondary">
        {currentView.description}
      </Typography.Text>
    </div>
  );
}
