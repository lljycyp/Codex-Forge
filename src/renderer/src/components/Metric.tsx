import { Card, Typography } from "antd";

type MetricProps = {
  title: string;
  value: string | number;
  note?: string;
  statusText?: string;
  statusTone?: "green" | "amber";
};

const metricCardStyles = {
  body: {
    padding: "13px 14px"
  }
};

const statusToneClass = {
  green: "bg-green-100 text-green-700",
  amber: "bg-amber-100 text-amber-700"
} satisfies Record<NonNullable<MetricProps["statusTone"]>, string>;

export function Metric({ title, value, note, statusText, statusTone = "green" }: MetricProps) {
  return (
    <Card
      className="rounded-card border border-shell-line bg-slate-50 shadow-none"
      styles={metricCardStyles}
    >
      <div className="flex items-center justify-between gap-2">
        <Typography.Text type="secondary">{title}</Typography.Text>
        {statusText ? (
          <span
            className={`inline-flex h-[22px] items-center justify-center rounded-full px-2 text-[11.5px] font-extrabold ${statusToneClass[statusTone]}`}
          >
            {statusText}
          </span>
        ) : null}
      </div>
      <div className="mt-[9px] text-[27px] font-black leading-none text-gray-900">{value}</div>
      {note ? <div className="mt-2 text-[11.5px] text-slate-400">{note}</div> : null}
    </Card>
  );
}
