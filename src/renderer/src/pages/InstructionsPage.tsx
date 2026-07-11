import { useEffect, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Select,
  Space,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import { Edit3, FileText, Plus, Power, Trash2 } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";
import type { AppState, InstructionTemplate, InstructionTemplateState, ProfileSummary } from "../types";

const { TextArea } = Input;
const SYSTEM_PROFILE_NAME = "__system__";
const isMulti = (mode: AppState["launchMode"]) => mode === "multi";

const iconActionButtonClass =
  "flex items-center justify-center text-slate-500 hover:!text-brand-600";

type InstructionsPageProps = {
  appState: AppState;
  profiles: ProfileSummary[];
};

export function InstructionsPage({ appState, profiles }: InstructionsPageProps) {
  const { language, t } = useI18n();
  const [state, setState] = useState<InstructionTemplateState | null>(null);
  const [loading, setLoading] = useState(false);
  const [profileName, setProfileName] = useState(appState.activeProfile || profiles[0]?.name || SYSTEM_PROFILE_NAME);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<InstructionTemplate | null>(null);
  const [syncTemplate, setSyncTemplate] = useState<InstructionTemplate | null>(null);
  const [syncTargetProfile, setSyncTargetProfile] = useState("");
  const [actionKey, setActionKey] = useState("");
  const [form] = Form.useForm();

  const multiMode = isMulti(appState.launchMode);
  const noProfile = multiMode && !profileName;
  const acting = Boolean(actionKey);
  const targetPayload = multiMode ? { profileName } : {};
  const profileOptions = [
    { label: t("系统级配置"), value: SYSTEM_PROFILE_NAME },
    ...profiles.map((profile) => ({ label: profile.name, value: profile.name })),
  ];
  const accountOptions = profiles.map((profile) => ({ label: profile.name, value: profile.name }));

  useEffect(() => {
    if (multiMode && !profileName) {
      setProfileName(appState.activeProfile || profiles[0]?.name || SYSTEM_PROFILE_NAME);
    }
  }, [appState.activeProfile, multiMode, profileName, profiles]);

  const refresh = async () => {
    if (noProfile) {
      setState(null);
      return;
    }
    setLoading(true);
    try {
      setState(await invokeLauncher<InstructionTemplateState>("list_instruction_templates", targetPayload));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("读取指令模板失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [profileName, multiMode]);

  const saveTemplate = async () => {
    const values = await form.validateFields();
    await invokeLauncher("save_instruction_template", {
      ...targetPayload,
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
    setActionKey(`enable:${template.id}`);
    try {
      await invokeLauncher("enable_instruction_template", { ...targetPayload, id: template.id });
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("启用指令模板失败"));
    } finally {
      setActionKey("");
    }
  };

  const enableTemplateForAll = async (template: InstructionTemplate) => {
    setActionKey(`sync:${template.id}`);
    try {
      await invokeLauncher("enable_instruction_template", { ...targetPayload, id: template.id, scope: "all" });
      message.success(t("已复制到所有账号"));
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("同步指令模板失败"));
    } finally {
      setActionKey("");
    }
  };

  const syncTemplateToProfile = async () => {
    if (!syncTemplate || !syncTargetProfile) {
      return;
    }
    setActionKey(`sync-profile:${syncTemplate.id}`);
    try {
      await invokeLauncher("enable_instruction_template", {
        ...targetPayload,
        id: syncTemplate.id,
        scope: "profile",
        targetProfileName: syncTargetProfile,
      });
      message.success(t("已复制到指定账号"));
      setSyncTemplate(null);
      setSyncTargetProfile("");
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("同步指令模板失败"));
    } finally {
      setActionKey("");
    }
  };

  const disableTemplate = async () => {
    setActionKey("disable");
    try {
      await invokeLauncher("disable_instruction_template", targetPayload);
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("禁用指令模板失败"));
    } finally {
      setActionKey("");
    }
  };

  const disableTemplateForAll = async () => {
    setActionKey("disable-all");
    try {
      await invokeLauncher("disable_instruction_template", { scope: "all" });
      message.success(t("已同步到所有账号"));
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("禁用全部账号失败"));
    } finally {
      setActionKey("");
    }
  };

  const deleteTemplate = async (template: InstructionTemplate) => {
    Modal.confirm({
      title: t("删除指令模板"),
      content: language === "en-US" ? `Delete "${template.title}"?` : `确认删除「${template.title}」？`,
      okText: t("删除"),
      okButtonProps: { danger: true },
      cancelText: t("取消"),
      onOk: async () => {
        await invokeLauncher("delete_instruction_template", { ...targetPayload, id: template.id });
        await refresh();
      },
    });
  };

  return (
    <div className="grid gap-4 pb-8">
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-panel border border-shell-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
        <div className="min-w-[260px] flex-1">
          <div className="flex items-center gap-2 text-base font-bold text-slate-800">
            <FileText size={18} />
            {t("指令模板")}
            {multiMode ? (
              <span className="rounded-[6px] border border-brand-100 bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-600">
                {t("多开")}
              </span>
            ) : null}
          </div>
          <Tooltip title={state?.activeConfigPath}>
            <div className="mt-1 truncate text-xs text-slate-500">
              {noProfile ? t("请选择账号后管理模板") : `${t("当前配置：")}${state?.activeConfigPath || t("读取中")}`}
            </div>
          </Tooltip>
        </div>
        <div className="flex max-w-full flex-wrap items-center justify-end gap-2 max-[960px]:w-full max-[960px]:justify-start">
          {multiMode ? (
            <Select
              className="w-[292px] max-w-full"
              value={profileName || undefined}
              placeholder={t("选择账号")}
              options={profileOptions}
              onChange={setProfileName}
            />
          ) : null}
          <Button type="primary" icon={<Plus size={15} />} onClick={openCreate}>
            {t("新增模板")}
          </Button>
          <Button
            icon={<Power size={15} />}
            disabled={noProfile || acting || !state?.currentInstructionFile}
            loading={actionKey === "disable"}
            onClick={disableTemplate}
          >
            {t("禁用当前")}
          </Button>
          {multiMode ? (
            <Button
              icon={<Power size={15} />}
              disabled={noProfile || acting}
              loading={actionKey === "disable-all"}
              onClick={disableTemplateForAll}
            >
              {t("全部禁用")}
            </Button>
          ) : null}
        </div>
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
                      {t("已启用")}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 truncate font-mono text-xs text-slate-400">
                  {template.filename}
                </div>
              </div>
              <Space.Compact className="max-[960px]:w-full">
                <Button
                  type="primary"
                  disabled={noProfile || acting || template.enabled}
                  loading={actionKey === `enable:${template.id}`}
                  icon={<Power size={14} />}
                  onClick={() => enableTemplate(template)}
                >
                  {t("启用")}
                </Button>
                {multiMode ? (
                  <Button
                    disabled={noProfile || acting}
                    loading={actionKey === `sync:${template.id}`}
                    onClick={() => enableTemplateForAll(template)}
                  >
                    {t("同步全部")}
                  </Button>
                ) : null}
                {multiMode ? (
                  <Button
                    disabled={noProfile || acting || profiles.length === 0}
                    loading={actionKey === `sync-profile:${template.id}`}
                    onClick={() => {
                      setSyncTemplate(template);
                      setSyncTargetProfile(profiles[0]?.name || "");
                    }}
                  >
                    {t("同步到账号")}
                  </Button>
                ) : null}
                <Tooltip title={t("编辑")}>
                  <Button
                    className={iconActionButtonClass}
                    disabled={acting}
                    icon={<Edit3 size={14} />}
                    onClick={() => openEdit(template)}
                  />
                </Tooltip>
                <Tooltip title={t("删除")}>
                  <Button
                    className={`${iconActionButtonClass} !text-red-500 hover:!bg-red-50 hover:!text-red-600 hover:!border-red-200`}
                    disabled={acting || template.enabled}
                    icon={<Trash2 size={14} />}
                    onClick={() => deleteTemplate(template)}
                  />
                </Tooltip>
              </Space.Compact>
            </div>
          ))
        ) : (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
            <Empty description={noProfile ? t("请选择账号后查看模板状态") : t("暂无指令模板")}>
              <Button type="primary" icon={<Plus size={16} />} onClick={openCreate}>
                {t("新增第一个模板")}
              </Button>
            </Empty>
          </div>
        )}
      </div>

      <Modal
        title={editingTemplate ? t("编辑指令模板") : t("新增指令模板")}
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          setEditingTemplate(null);
          form.resetFields();
        }}
        onOk={saveTemplate}
        okText={t("保存")}
        cancelText={t("取消")}
        width={720}
      >
        <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
          {language === "en-US"
            ? "In multi-instance mode this is saved to the current account. After enabling, it is copied to the current Codex config folder and written as model_instructions_file."
            : "多开模式会保存到当前账号；启用后会复制到当前 Codex 配置目录，并写入 model_instructions_file。"}
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label={t("模板名称")}
            rules={[{ required: true, message: t("请输入模板名称") }]}
          >
            <Input placeholder={t("例如：代码审查助手")} />
          </Form.Item>
          <Form.Item name="filename" label={t("文件名")}>
            <Input placeholder={t("留空时按模板名称自动生成")} />
          </Form.Item>
          <Form.Item
            name="content"
            label={t("模板内容")}
            rules={[{ required: true, message: t("请输入模板内容") }]}
          >
            <TextArea rows={12} placeholder={t("输入你自己的 Codex 指令模板")} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={t("同步到账号")}
        open={Boolean(syncTemplate)}
        onCancel={() => {
          setSyncTemplate(null);
          setSyncTargetProfile("");
        }}
        onOk={syncTemplateToProfile}
        okText={t("同步")}
        cancelText={t("取消")}
        okButtonProps={{ disabled: !syncTargetProfile }}
      >
        <Select
          className="w-full"
          value={syncTargetProfile || undefined}
          placeholder={t("选择目标账号")}
          options={accountOptions}
          onChange={setSyncTargetProfile}
        />
      </Modal>
    </div>
  );
}
