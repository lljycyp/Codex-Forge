import { Alert, Button, Card, Descriptions, Empty, List, Space, Tag } from "antd";
import { RefreshCw } from "lucide-react";
import { diagnosticBasicLabels } from "../constants/views";
import type { DiagnosticsData } from "../types";

type DiagnosticsProps = {
  diagnostics: DiagnosticsData | null;
  loadDiagnostics: () => Promise<void>;
  loading: boolean;
};

export function Diagnostics({ diagnostics, loadDiagnostics, loading }: DiagnosticsProps) {
  return (
    <Space direction="vertical" className="full" size={16}>
      <Alert message="诊断结果来自 Python 核心逻辑，可用于检查配置、路径、程序副本和账号目录。" type="info" showIcon />
      <Button icon={<RefreshCw size={16} />} loading={loading} onClick={loadDiagnostics}>
        重新诊断
      </Button>
      {diagnostics ? (
        <>
          <Card title="基础信息">
            <Descriptions column={2} size="small">
              {Object.entries(diagnostics.basic).map(([key, value]) => (
                <Descriptions.Item key={key} label={diagnosticBasicLabels[key] ?? key}>
                  {formatDiagnosticValue(value)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Card>
          <Card title="账号状态">
            <List
              dataSource={diagnostics.profiles}
              locale={{ emptyText: "暂无账号" }}
              renderItem={(profile) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <Space>
                        {profile.name}
                        <Tag>{profile.statusText}</Tag>
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={2}>
                        <span>{profile.profileDir}</span>
                        <span>磁盘占用：{profile.diskUsageText}</span>
                        <span>{[...profile.errors, ...profile.warnings].join("；") || "未发现明显问题"}</span>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </>
      ) : (
        <Empty description="尚未生成诊断" />
      )}
    </Space>
  );
}

function formatDiagnosticValue(value: string | number | boolean) {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value);
}
