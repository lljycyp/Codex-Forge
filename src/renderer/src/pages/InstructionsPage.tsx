import { useEffect, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Space,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import { Edit3, FileText, Plus, Power, RefreshCw, Trash2 } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import type { InstructionTemplate, InstructionTemplateState } from "../types";

const { TextArea } = Input;

const iconActionButtonClass =
  "flex items-center justify-center text-slate-500 hover:!text-brand-600";

export function InstructionsPage() {
  const [state, setState] = useState<InstructionTemplateState | null>(null);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<InstructionTemplate | null>(null);
  const [form] = Form.useForm();

  const refresh = async () => {
    setLoading(true);
    try {
      setState(await invokeLauncher<InstructionTemplateState>("list_instruction_templates"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取指令模板失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const saveTemplate = async () => {
    const values = await form.validateFields();
    await invokeLauncher("save_instruction_template", {
      ...values,
      id: editingTemplate?.id,
    });
    setCreateOpen(false);
    setEditingTemplate(null);
    form.resetFields();
    await refresh();
  };

  const openCreate = () => {
    setEditingTemplate(null);
    form.resetFields();
    setCreateOpen(true);
  };

  const openEdit = (template: InstructionTemplate) => {
    setEditingTemplate(template);
    form.setFieldsValue({
      title: template.title,
      filename: template.filename,
      content: template.content,
    });
    setCreateOpen(true);
  };

  const enableTemplate = async (template: InstructionTemplate) => {
    await invokeLauncher("enable_instruction_template", { id: template.id });
    await refresh();
  };

  const disableTemplate = async () => {
    await invokeLauncher("disable_instruction_template");
    await refresh();
  };

  const deleteTemplate = async (template: InstructionTemplate) => {
    Modal.confirm({
      title: "删除指令模板",
      content: `确认删除「${template.title}」？`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        await invokeLauncher("delete_instruction_template", { id: template.id });
        await refresh();
      },
    });
  };

  return (
    <div className="grid gap-4 pb-8">
      <div className="flex items-center justify-between gap-3 rounded-panel border border-shell-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(15,23,42,0.045)] max-[960px]:items-start max-[960px]:flex-col">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-base font-bold text-slate-800">
            <FileText size={18} />
            指令模板
          </div>
          <Tooltip title={state?.activeConfigPath}>
            <div className="mt-1 truncate text-xs text-slate-500">
              当前配置：{state?.activeConfigPath || "读取中"}
            </div>
          </Tooltip>
        </div>
        <Space wrap>
          <Button icon={<RefreshCw size={15} />} loading={loading} onClick={refresh}>
            刷新
          </Button>
          <Button
            icon={<Power size={15} />}
            disabled={!state?.currentInstructionFile}
            onClick={disableTemplate}
          >
            禁用当前
          </Button>
          <Button type="primary" icon={<Plus size={15} />} onClick={openCreate}>
            新增模板
          </Button>
        </Space>
      </div>

      <div className="overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
        {loading && !state ? (
          <div className="flex min-h-[220px] items-center justify-center">
            <Spin />
          </div>
        ) : state?.templates.length ? (
          state.templates.map((template) => (
            <div
              key={template.id}
              className={template.enabled
                ? "flex items-center gap-4 border-b border-[#ecf1f6] bg-green-50/40 px-5 py-4 last:border-b-0 max-[960px]:items-start max-[960px]:flex-col"
                : "flex items-center gap-4 border-b border-[#ecf1f6] px-5 py-4 last:border-b-0 hover:bg-slate-50 max-[960px]:items-start max-[960px]:flex-col"}
            >
              <div className="min-w-0 flex-auto">
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-[15px] text-gray-900">{template.title}</strong>
                  {template.enabled ? (
                    <span className="rounded-[6px] border border-green-200 bg-green-50 px-2 py-1 text-[11.5px] font-bold leading-none text-green-600">
                      已启用
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-slate-400">
                  {template.filename}
                </div>
              </div>
              <Space.Compact>
                <Button
                  type="primary"
                  disabled={template.enabled}
                  icon={<Power size={14} />}
                  onClick={() => enableTemplate(template)}
                >
                  启用
                </Button>
                <Tooltip title="编辑">
                  <Button
                    className={iconActionButtonClass}
                    icon={<Edit3 size={14} />}
                    onClick={() => openEdit(template)}
                  />
                </Tooltip>
                <Tooltip title="删除">
                  <Button
                    className={`${iconActionButtonClass} !text-red-500 hover:!bg-red-50 hover:!text-red-600 hover:!border-red-200`}
                    disabled={template.enabled}
                    icon={<Trash2 size={14} />}
                    onClick={() => deleteTemplate(template)}
                  />
                </Tooltip>
              </Space.Compact>
            </div>
          ))
        ) : (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
            <Empty description="暂无指令模板">
              <Button type="primary" icon={<Plus size={16} />} onClick={openCreate}>
                新增第一个模板
              </Button>
            </Empty>
          </div>
        )}
      </div>

      <Modal
        title={editingTemplate ? "编辑指令模板" : "新增指令模板"}
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          setEditingTemplate(null);
          form.resetFields();
        }}
        onOk={saveTemplate}
        okText="保存"
        cancelText="取消"
        width={720}
      >
        <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
          模板内容会保存到启动器本地目录；启用后会复制到当前 Codex 配置目录，并写入 model_instructions_file。
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label="模板名称"
            rules={[{ required: true, message: "请输入模板名称" }]}
          >
            <Input placeholder="例如：代码审查助手" />
          </Form.Item>
          <Form.Item name="filename" label="文件名">
            <Input placeholder="留空时按模板名称自动生成" />
          </Form.Item>
          <Form.Item
            name="content"
            label="模板内容"
            rules={[{ required: true, message: "请输入模板内容" }]}
          >
            <TextArea rows={12} placeholder="输入你自己的 Codex 指令模板" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
